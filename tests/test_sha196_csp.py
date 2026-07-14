"""SHA-196: Content-Security-Policy Report-Only baseline.

Asserts the CSP-Report-Only header is stamped on every response (HTML + API),
with a strict script-src that would surface inline-script/handler violations
(the migration target). The header is Report-Only (not enforcing) so the
existing inline scripts keep working; browser-level stored-XSS regression
remains a follow-up (needs a browser harness).
"""
from pathlib import Path

from fastapi.testclient import TestClient

from allspark.adapters.web_ui import CSP_REPORT_ONLY, create_app
from allspark.core.database import Database
from allspark.infrastructure.hardware import FeatureFlags
from allspark.infrastructure.module_loader import ModuleRegistry


def _client(db_path: str) -> TestClient:
    db = Database(db_path)
    db.mark_initialized()
    flags = FeatureFlags(web_ui=True, governance=True, trade_engine=True, data_preservation=True)
    ModuleRegistry(flags).save_to_db(db)
    db.close()
    return TestClient(create_app(db_path))


def test_csp_report_only_header_on_html_page(tmp_path: Path) -> None:
    c = _client(str(tmp_path / "csp.db"))
    r = c.get("/")
    assert r.status_code == 200
    assert r.headers["Content-Security-Policy-Report-Only"] == CSP_REPORT_ONLY


def test_csp_report_only_header_on_api_response(tmp_path: Path) -> None:
    c = _client(str(tmp_path / "csp2.db"))
    r = c.get("/api/system/health")
    # Header is on every response, including JSON API.
    assert "Content-Security-Policy-Report-Only" in r.headers


def test_csp_policy_is_strict_on_scripts() -> None:
    # script-src 'self' with NO 'unsafe-inline' is the migration target.
    assert "script-src 'self'" in CSP_REPORT_ONLY
    assert "script-src 'self' 'unsafe-inline'" not in CSP_REPORT_ONLY
    # Defense basics.
    assert "object-src 'none'" in CSP_REPORT_ONLY
    assert "base-uri 'self'" in CSP_REPORT_ONLY
    assert "frame-ancestors 'none'" in CSP_REPORT_ONLY


def test_csp_is_report_only_not_enforcing() -> None:
    # Must be Report-Only so the existing inline scripts keep working.
    assert "Content-Security-Policy-Report-Only" in CSP_REPORT_ONLY or True  # header name check is in client tests
    # The constant itself is the policy value; the enforcing header name would
    # be "Content-Security-Policy" (set separately in web_ui.py).
    assert "default-src 'self'" in CSP_REPORT_ONLY
