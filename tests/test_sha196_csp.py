"""SHA-213: enforcing Content-Security-Policy contract and inventory gate."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from allspark.adapters.web_ui import TEMPLATES_DIR, build_csp_policy, create_app
from allspark.core.database import Database
from allspark.infrastructure.hardware import FeatureFlags
from allspark.infrastructure.module_loader import ModuleRegistry


def _initialized_db(db_path: Path) -> None:
    db = Database(db_path)
    db.mark_initialized()
    flags = FeatureFlags(
        web_ui=True,
        governance=True,
        trade_engine=True,
        data_preservation=True,
    )
    ModuleRegistry(flags).save_to_db(db)
    db.close()


def _client(db_path: Path, *, token: str | None = None) -> TestClient:
    _initialized_db(db_path)
    return TestClient(create_app(str(db_path), token=token))


def _assert_enforcing(response) -> str:
    assert "Content-Security-Policy-Report-Only" not in response.headers
    policy = response.headers["Content-Security-Policy"]
    assert "script-src 'self' 'nonce-" in policy
    assert "script-src-attr 'none'" in policy
    assert "'unsafe-inline'" not in policy.split("script-src", 1)[1].split(";", 1)[0]
    assert "object-src 'none'" in policy
    assert "base-uri 'self'" in policy
    assert "frame-ancestors 'none'" in policy
    return policy


def _policy_nonce(policy: str) -> str:
    match = re.search(r"'nonce-([^']+)'", policy)
    assert match is not None
    return match.group(1)


def test_enforcing_csp_nonce_matches_every_rendered_script(tmp_path: Path) -> None:
    client = _client(tmp_path / "html.db")

    for path in ("/", "/system", "/config", "/executions", "/repository"):
        response = client.get(path)
        assert response.status_code == 200
        nonce = _policy_nonce(_assert_enforcing(response))
        script_nonces = re.findall(r'<script\b[^>]*\bnonce="([^"]+)"', response.text)
        assert script_nonces
        assert set(script_nonces) == {nonce}


def test_csp_uses_a_fresh_nonce_for_each_request(tmp_path: Path) -> None:
    client = _client(tmp_path / "nonce.db")
    first = _policy_nonce(_assert_enforcing(client.get("/")))
    second = _policy_nonce(_assert_enforcing(client.get("/")))
    assert first != second


def test_enforcing_csp_covers_api_auth_and_bootstrap_errors(tmp_path: Path) -> None:
    local = _client(tmp_path / "errors.db")
    health = local.get("/api/system/health")
    assert health.status_code == 200
    _assert_enforcing(health)

    missing = local.get("/api/knowledge/not-a-real-entry")
    assert missing.status_code == 404
    _assert_enforcing(missing)

    bootstrap_closed = local.post("/api/init/complete", json={})
    assert bootstrap_closed.status_code == 410
    _assert_enforcing(bootstrap_closed)

    protected = _client(tmp_path / "auth.db", token="audit-secret")
    unauthorized = protected.get("/api/system/health")
    assert unauthorized.status_code == 401
    _assert_enforcing(unauthorized)

    redirect = protected.get("/system", follow_redirects=False)
    assert redirect.status_code == 303
    _assert_enforcing(redirect)

    login = protected.get("/login")
    assert login.status_code == 200
    login_nonce = _policy_nonce(_assert_enforcing(login))
    assert f'nonce="{login_nonce}"' in login.text


def test_script_policy_is_strict_and_keeps_style_boundary_separate() -> None:
    policy = build_csp_policy("test-nonce")
    script_directive = next(
        directive for directive in policy.split("; ") if directive.startswith("script-src ")
    )
    assert script_directive == "script-src 'self' 'nonce-test-nonce'"
    assert "script-src-attr 'none'" in policy
    assert "style-src 'self' 'unsafe-inline'" in policy


def test_template_script_and_event_handler_inventory_cannot_regress() -> None:
    templates = sorted(TEMPLATES_DIR.glob("*.html"))
    sources = {path.name: path.read_text(encoding="utf-8") for path in templates}
    script_tags = [
        tag
        for source in sources.values()
        for tag in re.findall(r"<script\b[^>]*>", source, flags=re.IGNORECASE)
    ]

    assert len(script_tags) == 8
    assert all('nonce="{{ csp_nonce }}"' in tag for tag in script_tags)
    for name, source in sources.items():
        assert not re.search(r"\son[a-z]+\s*=", source, flags=re.IGNORECASE), name
        assert not re.search(
            r"\.on(?:click|input|change|keydown)\s*=", source, flags=re.IGNORECASE
        ), name
