"""AS-02: separate application instances must never share authentication state."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from allspark.adapters.web_ui import create_app


@pytest.mark.parametrize("tokens", [("alpha", None), (None, "alpha"), ("alpha", "bravo")])
def test_auth_configuration_is_isolated_in_both_request_orders(tmp_path: Path, tokens):
    apps = [create_app(str(tmp_path / f"{i}.db"), token=token) for i, token in enumerate(tokens)]
    try:
        for index in (0, 1, 1, 0):
            app, token = apps[index], tokens[index]
            with TestClient(app, follow_redirects=False) as client:
                assert client.get("/").status_code == (303 if token else 200)
                assert client.get("/api/init/status").status_code == (401 if token else 200)
                if token:
                    assert client.post("/api/auth/login", json={"token": token}).status_code == 200
                    assert client.cookies.get("allspark_session") == token
                    assert client.get("/api/init/status").status_code == 200
                    client.cookies.clear()
                    assert client.get("/api/init/status", headers={"Authorization": f"Bearer {token}"}).status_code == 200
                    other = tokens[1 - index] or "not-the-token"
                    assert client.post("/api/auth/login", json={"token": other}).status_code == 401
                    client.cookies.set("allspark_session", other)
                    rejected = client.get("/api/init/status", headers={"Authorization": f"Bearer {other}"})
                    assert rejected.status_code == 401
                    assert "Content-Security-Policy" in rejected.headers
                else:
                    assert client.post("/api/auth/login", json={"token": tokens[1 - index]}).status_code == 401
                assert app.state.web_token == token
    finally:
        for app in apps:
            app.state.db.close()
