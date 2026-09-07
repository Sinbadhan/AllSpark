"""Raw requests deliberately do not use the authorized API-client helper."""
import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from allspark.adapters.web_ui import create_app
from allspark.core.database import Database
from allspark.core.i18n import set_language
from tests.test_sha196_browser import _Chrome, _chrome_binary, _serve


@pytest.fixture
def client(tmp_path: Path):
    path = tmp_path / "boundary.db"
    db = Database(path)
    db.mark_initialized()
    db.close()
    app = create_app(str(path))
    try:
        with TestClient(app, base_url="http://127.0.0.1:8000") as client:
            yield client
    finally:
        app.state.db.close()


@pytest.mark.parametrize("headers,status", [
    ({"Origin": "https://evil.example"}, 403),
    ({"Origin": "null"}, 403),
    ({"Origin": "http://127.0.0.1:8001"}, 403),
    ({"Origin": "http://127.0.0.1:8000.evil.example"}, 403),
    ({"Origin": "http://127.0.0.1:8000/path"}, 403),
    ({"Origin": "http://user@127.0.0.1:8000"}, 403),
    ({"Referer": "https://evil.example/form"}, 403),
    ({"Host": "evil.example:8000"}, 400),
    ({"Host": "127.0.0.1:9999"}, 400),
    ({"Host": "[broken"}, 400),
    ({"Host": "user@127.0.0.1:8000"}, 400),
    ({"Sec-Fetch-Site": "cross-site"}, 403),
    ({"Host": "evil.example:8000", "X-Forwarded-Host": "127.0.0.1:8000"}, 400),
])
def test_foreign_requests_never_write_even_with_api_markers(client, headers, status):
    before = tuple(client.app.state.db.conn.iterdump())
    response = client.post("/api/resources", json={"type": "water", "amount": 3},
                           headers={"X-AllSpark-Request": "1", **headers})
    assert response.status_code == status
    assert "script-src-attr 'none'" in response.headers["Content-Security-Policy"]
    assert tuple(client.app.state.db.conn.iterdump()) == before


@pytest.mark.parametrize("headers", [
    {}, {"Content-Type": "text/plain"},
    {"Content-Type": "application/x-www-form-urlencoded"},
    {"Content-Type": "multipart/form-data; boundary=x"},
])
def test_simple_requests_without_origin_fail_closed(client, headers):
    before = tuple(client.app.state.db.conn.iterdump())
    response = client.post("/api/resources?type=water&amount=3", headers=headers)
    assert response.status_code == 403
    assert tuple(client.app.state.db.conn.iterdump()) == before


@pytest.mark.parametrize("headers", [
    {"Origin": "http://127.0.0.1:8000"},
    {"Referer": "http://127.0.0.1:8000/config?q=1"},
    {"X-AllSpark-Request": "1"},
    {"Content-Type": "application/json"},
])
def test_supported_browser_and_explicit_api_writes_work(client, headers):
    assert client.post("/api/resources?type=water&amount=3", headers=headers).status_code == 200


@pytest.mark.parametrize("language", ["zh", "en"])
def test_boundary_errors_are_localized_and_preflight_does_not_enable_cors(client, language):
    set_language(language, persist=False)
    response = client.post("/api/resources", headers={"Origin": "null"})
    assert response.status_code == 403
    assert response.json()["detail"] != "error_cross_origin_request"
    assert ("请求" in response.json()["detail"]) == (language == "zh")
    response = client.options("/api/resources", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "X-AllSpark-Request",
    })
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("base", ["http://localhost:8080", "http://127.0.0.1:8080", "http://[::1]:8080"])
def test_local_authority_address_matrix(tmp_path, base):
    app = create_app(str(tmp_path / "address.db"))

    async def probe():
        # httpx ASGITransport preserves IPv6 authorities. The installed
        # Starlette TestClient splits an IPv6 netloc on the first colon before
        # the application runs, so it cannot verify this address matrix.
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=base) as c:
            assert (await c.get("/")).status_code == 200
            assert (await c.post("/api/auth/logout", headers={"Origin": base})).status_code == 200

    try:
        asyncio.run(probe())
    finally:
        app.state.db.close()


def test_login_logout_and_bootstrap_share_the_boundary(tmp_path):
    app = create_app(str(tmp_path / "auth.db"), token="secret")
    try:
        with TestClient(app, base_url="http://localhost:8080") as c:
            for endpoint in ("/api/auth/login", "/api/auth/logout", "/api/init/complete", "/api/init/draft"):
                r = c.post(endpoint, json={"token": "secret"}, headers={"Origin": "null"})
                assert r.status_code == 403
                assert "set-cookie" not in r.headers
            assert c.post("/api/auth/login", json={"token": "secret"}).status_code == 200
            # A valid explicit Bearer client can use a query/no-body endpoint.
            assert c.post("/api/auth/logout", headers={"Authorization": "Bearer secret"}).status_code == 200
            assert app.state.db.is_initialized() is False
    finally:
        app.state.db.close()


def test_actual_http_and_cross_origin_chrome_form_cannot_mutate(client, tmp_path):
    # This is installed headless Chrome automation, not the separately required
    # user-selected Chrome/VoiceOver acceptance in AS-12.
    with _serve(client.app) as victim, _serve(create_app(str(tmp_path / "foreign.db"))) as foreign:
        before = tuple(client.app.state.db.conn.iterdump())
        with httpx.Client(base_url=victim) as wire:
            assert wire.post("/api/resources?type=water&amount=7").status_code == 403
            assert wire.post("/api/resources", json={"type": "water", "amount": 7},
                             headers={"Host": "attacker.example"}).status_code == 400
            assert wire.post("/api/resources", json={"type": "water", "amount": 7},
                             headers={"Origin": foreign}).status_code == 403
        with _Chrome(_chrome_binary(), tmp_path / "chrome-boundary") as browser:
            browser.call("Emulation.setDeviceMetricsOverride", {"width": 1280, "height": 768,
                         "deviceScaleFactor": 1, "mobile": False})
            browser.navigate(foreign)
            browser.wait_for("document.readyState === 'complete'")
            # Native form submission is not gated by the foreign page's fetch
            # CSP. It reaches the server as a real cross-origin simple POST.
            import json

            target = json.dumps(victim + "/api/resources?type=water&amount=7")
            browser.evaluate("const f=document.createElement('form'); f.method='POST';"
                             f"f.action={target}; document.body.appendChild(f); f.submit();")
            browser.wait_for("document.body.textContent.includes('cross_origin_request')")
        assert tuple(client.app.state.db.conn.iterdump()) == before
