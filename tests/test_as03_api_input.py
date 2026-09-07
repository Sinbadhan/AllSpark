"""AS-03: malformed API input is a localized client error with zero writes."""
import json
from pathlib import Path

import pytest

from allspark.adapters.web_ui import create_app
from allspark.core.database import Database
from allspark.core.i18n import set_language
from tests.http_helpers import LocalAPIClient


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    path: Path = tmp_path_factory.mktemp("input") / "api.db"
    db = Database(path)
    db.mark_initialized()
    db.close()
    app = create_app(str(path))
    try:
        with LocalAPIClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.state.db.close()


@pytest.mark.parametrize("route", ["/api/resources", "/api/chat", "/api/chat/stream", "/api/goals/add", "/api/diary/add"])
@pytest.mark.parametrize("raw", ['{', 'null', '[]', '"scalar"', '12', 'true'])
def test_json_shape_errors_do_not_write(client, route, raw):
    before = tuple(client.app.state.db.conn.iterdump())
    response = client.post(route, content=raw, headers={"Content-Type": "application/json"})
    assert response.status_code in (400, 422)
    assert response.json()["status"] == "error"
    assert tuple(client.app.state.db.conn.iterdump()) == before


@pytest.mark.parametrize("route", ["/api/chat", "/api/chat/stream"])
@pytest.mark.parametrize("body", [
    {}, {"message": None}, {"message": []}, {"message": 2}, {"message": True},
    {"message": "hello", "language": []}, {"message": "hello", "language": "invalid"},
])
def test_chat_fields_are_checked_before_language_or_engine_side_effects(client, route, body):
    before = tuple(client.app.state.db.conn.iterdump())
    assert client.post(route, json=body).status_code == 422
    assert tuple(client.app.state.db.conn.iterdump()) == before


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, [], True])
def test_resource_values_keep_service_validation(client, value):
    before = tuple(client.app.state.db.conn.iterdump())
    response = client.post("/api/resources", content=json.dumps({"type": "water", "amount": value}),
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert tuple(client.app.state.db.conn.iterdump()) == before


@pytest.mark.parametrize("language", ["zh", "en"])
def test_error_localization_and_success_contract(client, language):
    set_language(language, persist=False)
    response = client.post("/api/chat", content="{", headers={"Content-Type": "application/json"})
    assert response.status_code == 400
    assert ("JSON" in response.text) and ("无效" in response.text) == (language == "zh")
    assert client.post("/api/resources", json={"type": "water", "amount": 4}).json() == {"status": "ok"}
    assert any(item["type"] == "water" and item["amount"] == 4 for item in client.get("/api/resources").json())


def test_wrong_media_type_is_explicit(client):
    assert client.post("/api/chat", content='{"message":"hi"}', headers={"Content-Type": "text/plain"}).status_code == 415


@pytest.mark.parametrize("route,field,valid", [
    ("/api/goals/add", "title", {"title": "Water"}),
    ("/api/goals/add", "description", {"title": "Water"}),
    ("/api/goals/add", "priority", {"title": "Water"}),
    ("/api/goals/add", "category", {"title": "Water"}),
    ("/api/diary/add", "content", {"content": "Test note"}),
    ("/api/diary/add", "emotion", {"content": "Test note"}),
    ("/api/diary/add", "related_goal_id", {"content": "Test note"}),
    ("/api/system/language", "language", {}),
])
@pytest.mark.parametrize("value", [None, [], 12, True])
def test_mutation_field_types_are_rejected_without_partial_writes(client, route, field, valid, value):
    before = tuple(client.app.state.db.conn.iterdump())
    response = client.post(route, json={**valid, field: value})
    assert response.status_code in (400, 422)
    assert tuple(client.app.state.db.conn.iterdump()) == before


@pytest.mark.parametrize("route,body", [
    ("/api/goals/add", {}), ("/api/goals/add", {"title": "  "}),
    ("/api/goals/add", {"title": "Water", "priority": "invalid"}),
    ("/api/diary/add", {}), ("/api/diary/add", {"content": "  "}),
])
def test_required_text_and_priority_contract(client, route, body):
    before = tuple(client.app.state.db.conn.iterdump())
    assert client.post(route, json=body).status_code == 422
    assert tuple(client.app.state.db.conn.iterdump()) == before


def test_non_ascii_auth_input_is_unauthorized_not_a_server_error(tmp_path):
    app = create_app(str(tmp_path / "auth.db"), token="ascii-secret")
    try:
        with LocalAPIClient(app, raise_server_exceptions=False) as client:
            assert client.post("/api/auth/login", json={"token": "火种"}).status_code == 401
            assert client.get("/api/system/info", headers={"Cookie": 'allspark_session="\\377"'}).status_code == 401
    finally:
        app.state.db.close()
