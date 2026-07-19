"""Regression coverage for the 2026-07-20 task and plan contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient

from allspark.adapters.web_ui import create_app
from allspark.core.database import Database
from allspark.core.models import ResourceType


def _client(path: Path) -> TestClient:
    db = Database(path)
    try:
        db.mark_initialized()
    finally:
        db.close()
    return TestClient(create_app(str(path)))


def _app(client: TestClient) -> Any:
    return cast(Any, client.app)


def _publish_gap_task(client: TestClient, field: str = "urgency"):
    app = _app(client)
    container = app.state.container
    plan_service = container.get("survival_plan")
    plan = plan_service.generate_current()
    action_id = f"survival-plan-gap-{field}"
    assert action_id in {action.id for action in plan.actions}
    app.state.db.replace_active_survival_plan(plan, accepted_action_id=action_id)
    created = container.get("mission_planner").create_task_from_active_plan(plan_service)
    assert created is not None
    return created[0]


def _publish_low_water_plan(client: TestClient):
    app = _app(client)
    db = app.state.db
    manager = app.state.container.get("resource_manager")
    now = datetime.now(timezone.utc).isoformat()
    for key, value in {
        "people_count": "1",
        "people_count_status": "known",
        "health": "healthy",
        "health_status": "known",
        "urgency": "stable",
        "urgency_status": "known",
        "shelter": "permanent_building",
        "shelter_status": "known",
        "threats": "",
        "threats_status": "none",
    }.items():
        db.save_survivor_state(key, value)

    amounts = {
        ResourceType.WATER: 2,
        ResourceType.FOOD: 100,
        ResourceType.POWER: 100,
        ResourceType.FIRE: 10,
        ResourceType.STORAGE: 100,
    }
    for resource_type, amount in amounts.items():
        manager.update_resource(
            resource_type,
            amount,
            consumption=2 if resource_type == ResourceType.WATER else 1,
            intake=0,
            rate_basis="group_total",
            source="user_input",
            people_count=1,
            people_count_known=True,
            as_of=now,
            amount_known=True,
            consumption_known=True,
            intake_known=True,
        )

    plan_service = app.state.container.get("survival_plan")
    plan = plan_service.generate_current()
    action_id = "survival-plan-water-priority"
    assert action_id in {action.id for action in plan.actions}
    db.replace_active_survival_plan(plan, accepted_action_id=action_id)
    return plan_service, plan


def test_information_gap_rejects_unrelated_observation_and_accepts_named_fact(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path / "gap-correspondence.db")
    task = _publish_gap_task(client)

    unrelated = client.post(
        f"/api/tasks/{task.id}/complete",
        json={
            "result": "Counted water instead",
            "evidence": ["Bottle marks"],
            "resource_update": {"type": "water", "amount": 8},
            "confirm_resource_update": True,
        },
    )
    assert unrelated.status_code == 422
    assert unrelated.json()["errors"] == [{"field": "resource_update.type", "code": "information_gap_mismatch"}]
    assert unrelated.json()["context"]["expected_fields"] == ["urgency"]
    assert _app(client).state.db.get_task(task.id).status == "pending"

    completed = client.post(
        f"/api/tasks/{task.id}/complete",
        json={
            "result": "Confirmed current urgency",
            "fact_update": {
                "field": "urgency",
                "status": "known",
                "value": "stable",
            },
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["task"]["status"] == "completed"
    state = _app(client).state.db.get_survivor_state()
    assert state["urgency"] == "stable"
    assert state["urgency_status"] == "known"


def test_information_gap_requires_structured_update_or_explicit_unknown(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path / "gap-confirmation.db")
    task = _publish_gap_task(client)

    evidence_only = client.post(
        f"/api/tasks/{task.id}/complete",
        json={"result": "Looked around", "evidence": ["No useful observation"]},
    )
    assert evidence_only.status_code == 422
    assert evidence_only.json()["error_code"] == ("task_outcome.information_gap_update_required")

    explicit_unknown = client.post(
        f"/api/tasks/{task.id}/complete",
        json={
            "result": "Unable to determine urgency safely",
            "fact_update": {
                "field": "urgency",
                "status": "unknown",
                "confirm_unknown": True,
            },
        },
    )
    assert explicit_unknown.status_code == 200, explicit_unknown.text
    assert "confirmed_unknown:urgency" in _app(client).state.db.get_survivor_state()
    assert "survival-plan-gap-urgency" not in {action["id"] for action in explicit_unknown.json()["plan"]["actions"]}


def test_plan_payload_separates_fact_and_decision_rule_provenance(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path / "rule-provenance.db")
    plan_service, plan = _publish_low_water_plan(client)
    action = next(
        item for item in plan_service.payload(plan)["actions"] if item["id"] == "survival-plan-water-priority"
    )

    assert action["evidence"][0]["threshold_hours"] == 72
    assert "threshold_hours" not in action["fact_provenance"][0]
    assert action["fact_provenance"][0]["source"] == "user_input"
    rule = action["decision_rule_provenance"][0]
    assert rule == {
        "rule_id": "allspark.survival.resource_remaining.water",
        "version": "1.0.0",
        "review_status": "internal_review_pending_external",
        "threshold_hours": 72,
        "rationale": "prioritize_when_supply_is_below_three_days",
        "limitation": "depends_on_current_group_total_rates",
    }


def test_outcome_distinguishes_data_change_from_primary_action_change(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path / "primary-action.db")
    plan_service, old_plan = _publish_low_water_plan(client)
    created = _app(client).state.container.get("mission_planner").create_task_from_active_plan(plan_service)
    assert created is not None

    response = client.post(
        f"/api/tasks/{created[0].id}/complete",
        json={
            "result": "Recounted water",
            "evidence": ["Two people checked bottle levels"],
            "resource_update": {"type": "water", "amount": 3},
            "confirm_resource_update": True,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["plan"]["fingerprint"] != old_plan.fingerprint
    assert payload["plan_changed"] is True
    assert payload["plan_data_changed"] is True
    assert payload["previous_primary_action_id"] == ("survival-plan-water-priority")
    assert payload["new_primary_action_id"] == "survival-plan-water-priority"
    assert payload["primary_action_changed"] is False


def test_task_mismatch_exposes_stable_code_and_resource_context(tmp_path: Path) -> None:
    client = _client(tmp_path / "mismatch-context.db")
    _publish_low_water_plan(client)
    task, _ = (
        _app(client)
        .state.container.get("mission_planner")
        .create_task(
            title="Recount water",
            source="survival_plan",
            source_ref="contract:survival-plan-water-priority",
            evidence=["Water plan evidence"],
        )
    )

    response = client.post(
        f"/api/tasks/{task.id}/complete",
        json={
            "result": "Counted food",
            "evidence": ["Food inventory"],
            "resource_update": {"type": "food", "amount": 10},
            "confirm_resource_update": True,
        },
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "task_outcome.task_mismatch"
    assert response.json()["context"] == {
        "expected_resource": "water",
        "received_resource": "food",
    }
    assert response.json()["errors"] == [{"field": "resource_update.type", "code": "task_mismatch"}]
