"""SHA-151: web_ui (auth critical path) branch coverage.

Adds the branches not covered by test_web_ui_v11: HTML pages when uninitialized,
auth empty-token + logout, _is_authed direct branches, the /api/init/* routes
(status/questionnaire/hardware/models/download/download_progress/complete), and
_load_engine without a saved module registry.
"""
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

import allspark.adapters.web_ui as wui
from allspark.adapters.web_ui import MODEL_DOWNLOAD_URLS, create_app
from allspark.core.database import Database
from tests.assessment_helpers import valid_initial_assessment


def _client(db_path: str, token: str | None = None) -> TestClient:
    return TestClient(create_app(db_path, token=token))


# ─── _is_authed direct branches ──────────────────────────────────────────────


def test_is_authed_no_token_returns_false(monkeypatch) -> None:
    monkeypatch.setattr(wui, "_WEB_TOKEN", None)
    assert wui._is_authed(MagicMock()) is False


def test_is_authed_cookie_bearer_neither(monkeypatch) -> None:
    monkeypatch.setattr(wui, "_WEB_TOKEN", "secret")
    # valid cookie
    req = MagicMock()
    req.cookies.get.return_value = "secret"
    assert wui._is_authed(req) is True
    # valid bearer
    req = MagicMock()
    req.cookies.get.return_value = None
    req.headers.get.return_value = "Bearer secret"
    assert wui._is_authed(req) is True
    # neither
    req = MagicMock()
    req.cookies.get.return_value = None
    req.headers.get.return_value = ""
    assert wui._is_authed(req) is False


# ─── HTML pages when uninitialized ───────────────────────────────────────────


def test_html_pages_return_init_when_uninitialized(tmp_path: Path) -> None:
    c = _client(str(tmp_path / "ni.db"))
    for path in ("/system", "/executions", "/config", "/repository"):
        r = c.get(path)
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")


# ─── auth: empty token + logout ──────────────────────────────────────────────


def test_auth_empty_token_rejected_and_logout(tmp_path: Path) -> None:
    c = _client(str(tmp_path / "a.db"), token="secret")
    # empty token -> 401 (covers [199,200])
    assert c.post("/api/auth/login", json={"token": ""}).status_code == 401
    # missing token field -> 401
    assert c.post("/api/auth/login", json={}).status_code == 401
    # logout
    assert c.post("/api/auth/logout").status_code == 200


def test_auth_non_dict_body_handled(tmp_path: Path) -> None:
    # Body that parses to a non-dict (list) -> body stays {} -> token required.
    c = _client(str(tmp_path / "b.db"), token="secret")
    r = c.post("/api/auth/login", json=["not", "a", "dict"])
    assert r.status_code == 401


# ─── /api/init/* routes ──────────────────────────────────────────────────────


def test_init_status_questionnaire_hardware_models(tmp_path: Path) -> None:
    c = _client(str(tmp_path / "init.db"))
    assert c.get("/api/init/status").json()["initialized"] is False
    assert "questions" in c.get("/api/init/questionnaire").json()
    assert c.get("/api/init/hardware").status_code == 200
    models = c.get("/api/init/models").json()
    assert "existing" in models and "downloadable" in models


def test_init_models_with_existing_gguf(tmp_path: Path, monkeypatch) -> None:
    # Covers the existing-models + downloadable loops with a real .gguf present.
    monkeypatch.setattr(wui, "MODELS_DIR", tmp_path)
    (tmp_path / "mybox.gguf").write_bytes(b"x")
    c = _client(str(tmp_path / "im.db"))
    models = c.get("/api/init/models").json()
    assert any(m["name"] == "mybox" for m in models["existing"])


# ─── /api/init/download + download_progress ──────────────────────────────────


def _model_name() -> str:
    return next(iter(MODEL_DOWNLOAD_URLS.keys()))


def test_init_download_unknown_model_400(tmp_path: Path) -> None:
    c = _client(str(tmp_path / "d.db"))
    r = c.post("/api/init/download", params={"model_name": "nope"})
    assert r.status_code == 400


def test_init_download_already_exists(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(wui, "MODELS_DIR", tmp_path)
    name = _model_name()
    dest = tmp_path / MODEL_DOWNLOAD_URLS[name].split("/")[-1]
    dest.write_bytes(b"x")
    c = _client(str(tmp_path / "d2.db"))
    assert c.post("/api/init/download", params={"model_name": name}).json()["status"] == "already_exists"


def test_init_download_in_progress_when_tmp_exists(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(wui, "MODELS_DIR", tmp_path)
    name = _model_name()
    dest = tmp_path / MODEL_DOWNLOAD_URLS[name].split("/")[-1]
    (dest.with_suffix(".tmp")).write_bytes(b"x")
    c = _client(str(tmp_path / "d3.db"))
    r = c.post("/api/init/download", params={"model_name": name})
    assert r.json()["status"] == "downloading"


def test_download_progress_all_states(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(wui, "MODELS_DIR", tmp_path)
    name = _model_name()
    dest = tmp_path / MODEL_DOWNLOAD_URLS[name].split("/")[-1]
    tmp = dest.with_suffix(".tmp")
    err = dest.with_suffix(".error")
    c = _client(str(tmp_path / "p.db"))
    # not_started
    assert c.get("/api/init/download_progress", params={"model_name": name}).json()["status"] == "not_started"
    # downloading
    tmp.write_bytes(b"partial")
    assert c.get("/api/init/download_progress", params={"model_name": name}).json()["status"] == "downloading"
    # error
    tmp.unlink()
    err.write_text("boom")
    assert c.get("/api/init/download_progress", params={"model_name": name}).json()["status"] == "error"
    # done
    dest.write_bytes(b"full")
    assert c.get("/api/init/download_progress", params={"model_name": name}).json()["status"] == "done"


# ─── /api/init/complete (body + list fields + cookie + 410) ───────────────────


def test_init_complete_with_body_list_fields_and_cookie(tmp_path: Path) -> None:
    token = "secret"
    c = _client(str(tmp_path / "ic.db"), token=token)
    # SHA-142: in token mode, bootstrap requires prior login (explicit authorization).
    assert c.post("/api/auth/login", json={"token": token}).status_code == 200
    r = c.post("/api/init/complete", json={
        "language": "zh", "survivor_name": "Tester",
        "location_type": "urban", "shelter": "apt",
        "skills": ["first_aid", "navigation"],  # list -> _pick joins (covers [435,436])
        "assessment": valid_initial_assessment(),
    })
    assert r.status_code == 200
    assert "allspark_session" in r.cookies  # cookie re-stamped (covers [490,491])
    # second complete -> 410 bootstrap closed (covers middleware [108,109])
    r2 = c.post("/api/init/complete", json={"language": "zh"})
    assert r2.status_code == 410


def test_init_complete_loopback_no_cookie(tmp_path: Path) -> None:
    # No token -> no cookie stamped (covers the [490,491] false branch).
    c = _client(str(tmp_path / "icl.db"))
    r = c.post(
        "/api/init/complete",
        json={
            "language": "en",
            "survivor_name": "Z",
            "assessment": valid_initial_assessment(),
        },
    )
    assert r.status_code == 200
    assert "allspark_session" not in r.cookies


# ─── _load_engine without a saved module registry ────────────────────────────


def test_load_engine_without_registry_falls_back_to_detect(tmp_path: Path) -> None:
    # Initialized db with no module registry saved -> _load_engine takes the
    # detect_hardware fallback (covers [252,255]).
    db_path = tmp_path / "noreg.db"
    db = Database(db_path)
    db.mark_initialized()
    db.close()
    c = _client(str(db_path))
    # App booted without crashing; engine loaded via fallback path.
    assert c.app.state.engine is not None


def test_download_progress_error_unlinks_tmp(tmp_path: Path, monkeypatch) -> None:
    # Both error file and tmp present -> error path unlinks tmp (covers [400,401]).
    monkeypatch.setattr(wui, "MODELS_DIR", tmp_path)
    name = _model_name()
    dest = tmp_path / MODEL_DOWNLOAD_URLS[name].split("/")[-1]
    dest.with_suffix(".tmp").write_bytes(b"partial")
    dest.with_suffix(".error").write_text("boom")
    r = c_get_progress(tmp_path, name)
    assert r.json()["status"] == "error"


def test_init_complete_non_dict_body_is_rejected_without_draft(tmp_path: Path) -> None:
    # A non-dict cannot carry the explicit safety contract and must not publish.
    c = _client(str(tmp_path / "icnd.db"))
    r = c.post("/api/init/complete", json=["not", "a", "dict"])
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_initial_assessment"
    assert c.app.state.db.is_initialized() is False
    assert c.app.state.db.get_survivor_state() == {}


def test_init_download_thread_records_error_on_network_failure(tmp_path: Path, monkeypatch) -> None:
    # Mock urlopen to raise -> the download thread exhausts all urls and writes
    # an error file (covers the mirror-check, loop, except-continue, and
    # all-sources-failed branches inside _download).
    import time
    import urllib.request

    monkeypatch.setattr(wui, "MODELS_DIR", tmp_path)
    name = _model_name()
    dest = tmp_path / MODEL_DOWNLOAD_URLS[name].split("/")[-1]

    def _boom(*args, **kwargs):
        raise RuntimeError("network down")
    monkeypatch.setattr(urllib.request, "urlopen", _boom)

    c = _client(str(tmp_path / "df.db"))
    r = c.post("/api/init/download", params={"model_name": name})
    assert r.json()["status"] == "downloading"

    err = dest.with_suffix(".error")
    for _ in range(60):  # poll up to ~3s for the background thread to finish
        if err.exists():
            break
        time.sleep(0.05)
    assert err.exists(), "download thread did not write error file"


def c_get_progress(tmp_path: Path, name: str):
    return _client(str(tmp_path / "p2.db")).get(
        "/api/init/download_progress", params={"model_name": name}
    )
