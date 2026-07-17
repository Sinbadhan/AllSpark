from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from allspark.adapters.web_ui import create_app
from allspark.core.database import Database
from allspark.core.i18n import get_language, set_language
from allspark.core.models import ResourceType, Task
from allspark.services.initial_assessment import (
    InitialAssessmentService,
    validate_initial_assessment,
)
from allspark.services.resource_manager import ResourceManager
from allspark.services.survival_engine import SurvivalAssessmentEngine
from allspark.services.survival_plan import (
    SurvivalPlanService,
    SurvivalPlanValidationError,
)
from tests.assessment_helpers import valid_initial_assessment


def _assessment(*, confirmed: bool = True, complete_rates: bool = False) -> dict:
    payload = valid_initial_assessment(confirmed=confirmed)
    if complete_rates:
        amounts = {
            ResourceType.POWER.value: 1000,
            ResourceType.WATER.value: 100,
            ResourceType.FOOD.value: 20_000,
            ResourceType.FIRE.value: 10,
            ResourceType.STORAGE.value: 100,
        }
        consumption = {
            ResourceType.POWER.value: 100,
            ResourceType.WATER.value: 2,
            ResourceType.FOOD.value: 2_000,
            ResourceType.FIRE.value: 1,
            ResourceType.STORAGE.value: 1,
        }
        for domain, resource in payload["resources"].items():
            resource["amount"] = amounts[domain]
            resource["rates"] = {
                "status": "estimate",
                "basis": "group_total",
                "daily_consumption": consumption[domain],
                "daily_intake": 0,
            }
    payload["as_of"] = datetime.now(timezone.utc).isoformat()
    return validate_initial_assessment(payload, require_confirmation=confirmed)


def test_plan_is_deterministic_and_confirmation_is_not_assessment_evidence(
    tmp_path,
) -> None:
    db = Database(tmp_path / "plan.db")
    service = SurvivalPlanService(db, ResourceManager(db))
    preview = _assessment(confirmed=False)
    complete = deepcopy(preview)
    complete["confirmed"] = True

    first = service.generate(preview)
    second = service.generate(complete)

    assert first.id == second.id
    assert first.fingerprint == second.fingerprint
    assert first.phase is None
    assert first.phase_status == "unknown"
    assert first.actions
    assert all(action.id.startswith("survival-plan-") for action in first.actions)
    assert not any("remaining_hours" in item for item in first.actions for item in item.evidence)


def test_plan_phase_reuses_survival_assessment_truth(tmp_path, monkeypatch) -> None:
    db = Database(tmp_path / "shared-phase.db")
    manager = ResourceManager(db)
    manager.init_defaults()
    assessment = _assessment(complete_rates=True)
    InitialAssessmentService(db, manager).apply(assessment)

    monkeypatch.setattr(
        manager,
        "remaining_status",
        lambda _resource: (_ for _ in ()).throw(
            AssertionError("plan generation must not read a second clock")
        ),
    )
    plan = SurvivalPlanService(db, manager).generate(assessment)
    monkeypatch.undo()
    runtime = SurvivalAssessmentEngine(db, manager).assess()

    assert plan.phase == runtime["phase"]
    assert plan.phase_status == runtime["phase_status"]
    assert plan.phase is not None
    assert db.get_active_tasks() == []


def test_known_safety_danger_outranks_information_gaps_and_renders_requested_language(
    tmp_path,
) -> None:
    db = Database(tmp_path / "danger-plan.db")
    service = SurvivalPlanService(db, ResourceManager(db))
    assessment = _assessment(confirmed=False)
    assessment["urgency"] = {"status": "known", "value": "immediate_danger"}
    assessment["health"] = {"status": "unknown"}

    plan = service.generate(assessment)
    primary_ids = service.primary_candidate_ids(plan)
    payload = service.payload(plan, language="en")

    assert primary_ids == ["survival-plan-immediate_danger"]
    assert not any(action_id.startswith("survival-plan-gap-") for action_id in primary_ids)
    primary = next(action for action in payload["actions"] if action["id"] in primary_ids)
    assert primary["title"] == "Open the versioned immediate-danger flow"
    assert "external review is still pending" in primary["done_when_text"]
    assert primary["prerequisite_texts"]


def test_known_low_water_generates_evidence_based_primary_action(tmp_path) -> None:
    db = Database(tmp_path / "low-water-plan.db")
    service = SurvivalPlanService(db, ResourceManager(db))
    assessment = _assessment(confirmed=False, complete_rates=True)
    assessment["resources"]["water"]["amount"] = 2

    plan = service.generate(assessment)
    primary_ids = service.primary_candidate_ids(plan)

    assert "survival-plan-water-priority" in primary_ids
    action = next(item for item in plan.actions if item.id == "survival-plan-water-priority")
    assert action.evidence == [
        {
            "kind": "resource_snapshot",
            "resource": "water",
            "remaining_status": "finite",
            "amount": 2,
            "unit": "L",
            "daily_consumption": 2.0,
            "daily_intake": 0.0,
            "remaining_hours": 24.0,
            "threshold_hours": 72,
            "as_of": assessment["as_of"],
            "source": "user_input",
        }
    ]
    payload = service.payload(plan, language="en")
    rendered = next(
        item for item in payload["actions"] if item["id"] == action.id
    )
    assert "2 L / (2.0 - 0.0) L/day = 24.0 hours" in rendered["evidence_texts"][0]
    assert "threshold 72 hours" in rendered["evidence_texts"][0]


def test_single_missing_and_stale_facts_remain_explicit_plan_gaps(tmp_path) -> None:
    db = Database(tmp_path / "gap-plan.db")
    service = SurvivalPlanService(db, ResourceManager(db))
    missing = _assessment(confirmed=False, complete_rates=True)
    missing["resources"]["water"]["rates"] = {"status": "unknown"}

    missing_plan = service.generate(missing)
    missing_action = next(
        item for item in missing_plan.actions if item.id == "survival-plan-gap-water"
    )
    assert missing_plan.phase is None
    assert "water.consumption" in missing_plan.missing_fields
    assert not any("remaining_hours" in evidence for evidence in missing_action.evidence)

    stale = _assessment(confirmed=False, complete_rates=True)
    stale["as_of"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    stale_plan = service.generate(stale)
    stale_action = next(
        item for item in stale_plan.actions if item.id == "survival-plan-gap-water"
    )
    assert stale_plan.phase is None
    assert "water.as_of" in stale_plan.stale_fields
    assert {item["status"] for item in stale_action.evidence} == {"stale"}


def test_freshness_boundary_fails_closed_and_requires_latest_plan(tmp_path) -> None:
    db = Database(tmp_path / "boundary-plan.db")
    service = SurvivalPlanService(db, ResourceManager(db))
    assessment = _assessment(confirmed=False, complete_rates=True)
    boundary = datetime(2030, 1, 2, tzinfo=timezone.utc)
    assessment["as_of"] = (boundary - timedelta(hours=24) + timedelta(seconds=1)).isoformat()

    current = service.generate(assessment, now=boundary)
    expired = service.generate(assessment, now=boundary + timedelta(seconds=2))

    assert current.phase is not None
    assert expired.phase is None
    assert current.id != expired.id
    try:
        service.validate_selection(
            expired,
            plan_id=current.id,
            accepted_action_id=service.primary_candidate_ids(current)[0],
        )
    except SurvivalPlanValidationError as exc:
        assert (exc.field, exc.code) == ("plan_id", "stale_plan")
    else:
        raise AssertionError("an expired preview must require a current plan")


def test_legacy_gap_task_is_preserved_until_equivalent_plan_publish(tmp_path) -> None:
    path = tmp_path / "legacy-gap.db"
    db = Database(path)
    db.save_task(
        Task(
            id="assessment-gap-water",
            phase=0,
            priority=1,
            title="legacy gap",
            status="pending",
        )
    )
    db.conn.close()

    reopened = Database(path)
    assert [task.id for task in reopened.get_active_tasks()] == [
        "assessment-gap-water"
    ]
    service = SurvivalPlanService(reopened, ResourceManager(reopened))
    plan = service.generate(_assessment())
    selected = service.primary_candidate_ids(plan)[0]
    service.persist_draft(plan, plan_id=plan.id, accepted_action_id=selected)
    reopened.cleanup_initialization_plan_drafts()
    assert reopened.get_survival_plan() is None
    assert [task.id for task in reopened.get_active_tasks()] == [
        "assessment-gap-water"
    ]

    plan = service.generate(_assessment())
    selected = service.primary_candidate_ids(plan)[0]
    service.persist_draft(plan, plan_id=plan.id, accepted_action_id=selected)
    reopened.finalize_initialization("en", plan.id, selected)
    assert reopened.get_active_tasks() == []


def test_selection_persists_atomically_and_survives_restart(tmp_path) -> None:
    path = tmp_path / "restart.db"
    db = Database(path)
    service = SurvivalPlanService(db, ResourceManager(db))
    plan = service.generate(_assessment())
    selected = service.primary_candidate_ids(plan)[0]

    service.persist_draft(
        plan, plan_id=plan.id, accepted_action_id=selected
    )
    db.finalize_initialization("en", plan.id, selected)
    db.conn.close()

    reopened = Database(path)
    active = reopened.get_survival_plan(active_only=True)
    assert active is not None
    assert active.id == plan.id
    assert active.fingerprint == plan.fingerprint
    assert active.accepted_action_id == selected
    assert next(action for action in active.actions if action.id == selected).status == "accepted"


def test_selection_rejects_stale_plan_and_non_primary_action(tmp_path) -> None:
    db = Database(tmp_path / "reject.db")
    service = SurvivalPlanService(db, ResourceManager(db))
    plan = service.generate(_assessment())

    try:
        service.validate_selection(
            plan,
            plan_id="stale",
            accepted_action_id=service.primary_candidate_ids(plan)[0],
        )
    except SurvivalPlanValidationError as exc:
        assert exc.code == "stale_plan"
    else:
        raise AssertionError("stale plan must be rejected")

    lower_priority = next(
        action.id
        for action in plan.actions
        if action.id not in service.primary_candidate_ids(plan)
    )
    try:
        service.validate_selection(
            plan, plan_id=plan.id, accepted_action_id=lower_priority
        )
    except SurvivalPlanValidationError as exc:
        assert exc.code == "invalid_primary_action"
    else:
        raise AssertionError("non-primary action must be rejected")


def test_web_preview_requires_confirmed_plan_selection_before_publish(tmp_path) -> None:
    client = TestClient(create_app(str(tmp_path / "web.db")))
    assessment = valid_initial_assessment(confirmed=False)
    preview = client.post(
        "/api/init/assessment/preview",
        json={"language": "en", "assessment": assessment},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assessment["as_of"] = body["summary"]["as_of"]
    assessment["confirmed"] = True

    previous_language = get_language()
    set_language("zh", persist=False)
    try:
        missing = client.post(
            "/api/init/complete",
            json={"language": "en", "assessment": assessment},
        )
    finally:
        set_language(previous_language, persist=False)
    assert missing.status_code == 422
    assert missing.json()["error"] == "invalid_survival_plan"
    assert missing.json()["detail"] == "Select one primary action explicitly."
    assert client.app.state.db.is_initialized() is False

    selected = body["plan"]["primary_candidate_ids"][0]
    completed = client.post(
        "/api/init/complete",
        json={
            "language": "en",
            "assessment": assessment,
            "plan_id": body["plan"]["id"],
            "primary_action_id": selected,
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["created_task_ids"] == []
    assert completed.json()["plan"]["accepted_action_id"] == selected
    assert client.app.state.db.is_initialized() is True
    assert client.app.state.db.get_active_tasks() == []
    current = client.get("/api/survival-plan")
    assert current.status_code == 200
    assert current.json()["accepted_action_id"] == selected
    assert current.json()["actions"]
    html = client.get("/").text
    assert 'id="primary-plan"' in html
    assert 'aria-labelledby="primary-plan-heading"' in html
