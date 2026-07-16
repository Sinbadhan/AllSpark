"""SHA-242: confirmed resource facts and advice-to-task action loop."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from allspark.adapters.web_ui import create_app
from allspark.commands.knowledge import TaskCommand
from allspark.core.database import Database
from allspark.core.i18n import get_language, set_language
from allspark.core.models import ResourceType
from allspark.services.resource_manager import ResourceManager


@pytest.fixture(autouse=True)
def _restore_language():
    original = get_language()
    yield
    set_language(original, persist=False)


def _client(path: Path) -> TestClient:
    db = Database(path)
    try:
        db.mark_initialized()
    finally:
        db.close()
    return TestClient(create_app(str(path)))


def _chat(client: TestClient, message: str, conversation_id: str = "resource-flow"):
    response = client.post(
        "/api/chat",
        json={"message": message, "conversation_id": conversation_id},
    )
    assert response.status_code == 200
    return response.json()


def test_duration_fact_requires_context_and_confirmation_before_write(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path / "resource-flow.db")
    db = client.app.state.db
    before = db.get_resource(ResourceType.WATER)
    assert before is not None and before.amount_known is False

    first = _chat(client, "我们有两天饮用水")
    assert first["interaction"] == {
        "kind": "resource_update",
        "status": "needs_context",
        "resource": "water",
        "state_changed": False,
    }
    unchanged = db.get_resource(ResourceType.WATER)
    assert unchanged is not None and unchanged.amount_known is False

    second = _chat(client, "一共10升，2个人")
    assert second["interaction"]["status"] == "needs_confirmation"
    assert second["interaction"]["state_changed"] is False
    unchanged = db.get_resource(ResourceType.WATER)
    assert unchanged is not None and unchanged.amount_known is False

    applied = _chat(client, "确认")
    assert applied["interaction"]["status"] == "applied"
    assert applied["interaction"]["state_changed"] is True
    assert applied["interaction"]["resource"] == "water"
    assert applied["interaction"]["plan_id"]

    water = db.get_resource(ResourceType.WATER)
    assert water is not None
    assert water.current_amount == 10
    assert water.daily_consumption == 5
    assert water.daily_intake == 0
    assert water.rate_basis == "group_total"
    assert water.people_count == 2
    assert water.people_count_known is True
    assert water.amount_known is True
    assert water.consumption_known is True
    assert water.intake_known is True

    plan = db.get_survival_plan(active_only=True)
    assert plan is not None and plan.id == applied["interaction"]["plan_id"]
    event = db.conn.execute(
        "SELECT event_type, description FROM timeline_events "
        "ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    assert event is not None
    assert event["event_type"] == "resource_change"
    assert "water" in event["description"]


def test_cancelled_resource_draft_never_mutates_state(tmp_path: Path) -> None:
    client = _client(tmp_path / "resource-cancel.db")
    db = client.app.state.db

    _chat(client, "We have two days of drinking water", "cancel-flow")
    cancelled = _chat(client, "cancel", "cancel-flow")

    assert cancelled["interaction"] == {
        "kind": "resource_update",
        "status": "cancelled",
        "resource": "water",
        "state_changed": False,
    }
    water = db.get_resource(ResourceType.WATER)
    assert water is not None and water.amount_known is False


def test_conversations_are_isolated_and_confirmation_is_not_reusable(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path / "resource-isolation.db")

    _chat(client, "We have 12 L of water for 3 people, about 3 days", "tab-a")
    unrelated = _chat(client, "confirm", "tab-b")
    assert "interaction" not in unrelated

    applied = _chat(client, "confirm", "tab-a")
    assert applied["interaction"]["status"] == "applied"
    repeated = _chat(client, "confirm", "tab-a")
    assert "interaction" not in repeated


def test_knowledge_advice_can_create_one_idempotent_traceable_task(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path / "knowledge-task.db")
    knowledge_id = "survival/water/purification/boiling"

    created = client.post(
        "/api/tasks/from-knowledge",
        json={"knowledge_id": knowledge_id},
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["created"] is True
    assert payload["task"]["source"] == "knowledge"
    assert payload["task"]["source_ref"] == knowledge_id
    assert payload["task"]["phase_status"] in {"known", "unknown"}

    repeated = client.post(
        "/api/tasks/from-knowledge",
        json={"knowledge_id": knowledge_id},
    )
    assert repeated.status_code == 200
    assert repeated.json()["created"] is False
    assert repeated.json()["task"]["id"] == payload["task"]["id"]

    tasks = client.get("/api/tasks").json()
    matching = [task for task in tasks if task["source_ref"] == knowledge_id]
    assert len(matching) == 1


def test_invalid_knowledge_task_request_is_read_only(tmp_path: Path) -> None:
    client = _client(tmp_path / "invalid-knowledge-task.db")

    missing = client.post(
        "/api/tasks/from-knowledge",
        json={"knowledge_id": "not/a/real/entry"},
    )
    assert missing.status_code == 404
    assert client.get("/api/tasks").json() == []


def test_cli_uses_same_confirmed_resource_flow_and_can_add_manual_task(
    tmp_path: Path,
) -> None:
    set_language("en", persist=False)
    client = _client(tmp_path / "cli-action-loop.db")
    container = client.app.state.container
    engine = container.require("rule_engine")

    first = engine.process_input("We have 6 L water for 2 people, about 2 days", conversation_id="cli")
    assert "confirm" in first.lower()
    applied = engine.process_input("confirm", conversation_id="cli")
    assert "24-hour" in applied

    command = TaskCommand(container)
    command.console = MagicMock()
    command.execute(["add", "Inspect", "the", "water", "filter"])
    manual = [task for task in client.app.state.db.get_tasks() if task.source == "manual"]
    assert len(manual) == 1
    assert manual[0].title == "Inspect the water filter"


def test_confirmation_discloses_and_preserves_existing_rates(tmp_path: Path) -> None:
    client = _client(tmp_path / "preserve-rates.db")
    db = client.app.state.db
    manager = ResourceManager(db)
    manager.update_resource(
        ResourceType.WATER,
        20,
        consumption=2,
        intake=1,
        rate_basis="group_total",
        source="user_input",
        people_count=2,
        people_count_known=True,
        amount_known=True,
        consumption_known=True,
        intake_known=True,
    )

    draft = _chat(client, "We have 12 L water for 2 people", "preserve-rates")
    assert draft["interaction"]["status"] == "needs_confirmation"
    assert "2" in draft["response"] and "1" in draft["response"]
    _chat(client, "confirm", "preserve-rates")

    water = db.get_resource(ResourceType.WATER)
    assert water is not None
    assert water.current_amount == 12
    assert water.daily_consumption == 2
    assert water.daily_intake == 1


def test_storage_amount_update_preserves_confirmed_capacity(tmp_path: Path) -> None:
    client = _client(tmp_path / "preserve-capacity.db")
    db = client.app.state.db
    manager = ResourceManager(db)
    manager.update_resource(
        ResourceType.STORAGE,
        50,
        source="user_input",
        amount_known=True,
        capacity=100,
        capacity_known=True,
    )

    draft = _chat(client, "We have 60 GB storage", "preserve-capacity")
    assert "100" in draft["response"]
    _chat(client, "confirm", "preserve-capacity")

    storage = db.get_resource(ResourceType.STORAGE)
    assert storage is not None
    assert storage.current_amount == 60
    assert storage.capacity == 100
    assert storage.capacity_known is True


def test_active_task_contract_excludes_terminal_rows_by_default(tmp_path: Path) -> None:
    client = _client(tmp_path / "task-scope.db")
    task = client.post(
        "/api/tasks/from-knowledge",
        json={"knowledge_id": "survival/water/purification/boiling"},
    ).json()["task"]

    completed = client.post(
        f"/api/tasks/{task['id']}/complete",
        json={"result": "Reviewed the knowledge action"},
    )
    assert completed.status_code == 200
    active = client.get("/api/tasks").json()
    assert all(item["id"] != task["id"] for item in active)
    history = client.get("/api/tasks?include_terminal=true").json()
    completed_history = [item for item in history if item["id"] == task["id"]]
    assert len(completed_history) == 1
    assert completed_history[0]["status"] == "completed"

    template = (Path(__file__).parents[1] / "allspark/templates/index.html").read_text()
    assert "t.phase_status === 'known'" in template


def test_stream_route_uses_the_same_confirmation_boundary(tmp_path: Path) -> None:
    client = _client(tmp_path / "stream-action-loop.db")
    conversation_id = "stream-resource"

    first = client.post(
        "/api/chat/stream",
        json={
            "message": "We have two days of drinking water",
            "conversation_id": conversation_id,
        },
    )
    assert first.status_code == 200
    assert first.json()["interaction"]["status"] == "needs_context"

    second = client.post(
        "/api/chat/stream",
        json={"message": "10 L for 2 people", "conversation_id": conversation_id},
    )
    assert second.json()["interaction"]["status"] == "needs_confirmation"
    applied = client.post(
        "/api/chat/stream",
        json={"message": "confirm", "conversation_id": conversation_id},
    )
    assert applied.json()["interaction"]["status"] == "applied"
    water = client.app.state.db.get_resource(ResourceType.WATER)
    assert water is not None and water.current_amount == 10
