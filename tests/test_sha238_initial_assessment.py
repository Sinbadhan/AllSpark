"""SHA-238: shared, explicit first-run assessment contract."""

import math
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from allspark.adapters import web_ui as web_ui_module
from allspark.adapters.web_ui import create_app
from allspark.bootstrap import PreparedApplication
from allspark.container import ServiceContainer
from allspark.core.database import Database
from allspark.core.i18n import get_language, render, set_language
from allspark.core.models import ResourceType, Task
from allspark.services.initial_assessment import (
    InitialAssessmentService,
    InitialAssessmentValidationError,
    assessment_preview,
    validate_initial_assessment,
)
from allspark.services.resource_manager import ResourceManager
from allspark.services.survival_plan import SurvivalPlanService


def assessment_payload(*, confirmed: bool = True) -> dict:
    return {
        "people_count": {"status": "known", "value": 2},
        "health": {"status": "known", "value": "healthy"},
        "urgency": {"status": "known", "value": "stable"},
        "shelter": {"status": "known", "value": "permanent_building"},
        "threats": {"status": "none", "values": []},
        "resources": {
            resource.value: {
                "status": "known",
                "amount": 10,
                "rates": {"status": "unknown"},
            }
            for resource in ResourceType
        },
        "confirmed": confirmed,
    }


def unknown_assessment() -> dict:
    payload = assessment_payload()
    for field in ("people_count", "health", "urgency", "shelter"):
        payload[field] = {"status": "unknown"}
    payload["threats"] = {"status": "unknown", "values": []}
    payload["resources"] = {
        resource.value: {"status": "unknown", "rates": {"status": "unknown"}}
        for resource in ResourceType
    }
    return payload


@pytest.mark.parametrize(
    ("mutation", "field", "code"),
    [
        (lambda p: p.pop("health"), "health", "explicit_status_required"),
        (lambda p: p.update(health=""), "health", "explicit_status_required"),
        (
            lambda p: p.update(health={"status": "unknown", "value": "healthy"}),
            "health",
            "values_not_allowed",
        ),
        (
            lambda p: p.update(health={"status": "invalid"}),
            "health",
            "explicit_status_required",
        ),
        (
            lambda p: p.update(health={"status": "known", "value": "invalid"}),
            "health",
            "invalid_choice",
        ),
        (
            lambda p: p["people_count"].update(value=1.5),
            "people_count",
            "not_integer",
        ),
        (
            lambda p: p["people_count"].update(value=True),
            "people_count",
            "not_integer",
        ),
        (
            lambda p: p["people_count"].update(value=0),
            "people_count",
            "people_range",
        ),
        (
            lambda p: p["people_count"].update(value=10_001),
            "people_count",
            "people_range",
        ),
        (
            lambda p: p["resources"]["water"].update(amount=-1),
            "resources.water.amount",
            "negative",
        ),
        (
            lambda p: p["resources"]["water"].update(amount=math.nan),
            "resources.water.amount",
            "not_finite",
        ),
        (
            lambda p: p["resources"]["water"].update(amount=math.inf),
            "resources.water.amount",
            "not_finite",
        ),
        (
            lambda p: p["resources"]["water"].update(amount=True),
            "resources.water.amount",
            "not_numeric",
        ),
        (
            lambda p: p["resources"]["water"].update(amount=100_001),
            "resources.water.amount",
            "outlier_confirmation",
        ),
        (
            lambda p: p.update(confirmed=False),
            "confirmed",
            "confirmation_required",
        ),
    ],
)
def test_contract_rejects_invalid_or_implicit_values(mutation, field, code) -> None:
    payload = assessment_payload()
    mutation(payload)

    with pytest.raises(InitialAssessmentValidationError) as error:
        validate_initial_assessment(payload)

    assert {tuple(item.values()) for item in error.value.errors} >= {(field, code)}


@pytest.mark.parametrize("count", [1, 10_000, "2"])
def test_people_count_accepts_only_explicit_integer_semantics(count) -> None:
    payload = assessment_payload()
    payload["people_count"]["value"] = count
    assert validate_initial_assessment(payload)["people_count"]["value"] == int(count)


@pytest.mark.parametrize(
    ("threats", "normalized"),
    [
        ({"status": "none", "values": []}, {"status": "none", "values": []}),
        (
            {"status": "unknown", "values": []},
            {"status": "unknown", "values": []},
        ),
        (
            {"status": "selected", "values": ["flooding", "fire_risk"]},
            {"status": "selected", "values": ["flooding", "fire_risk"]},
        ),
    ],
)
def test_threats_have_three_explicit_states(threats, normalized) -> None:
    payload = assessment_payload()
    payload["threats"] = threats
    assert validate_initial_assessment(payload)["threats"] == normalized


@pytest.mark.parametrize(
    "threats",
    [
        {},
        {"status": "selected", "values": []},
        {"status": "none", "values": ["flooding"]},
        {"status": "selected", "values": ["not-a-threat"]},
    ],
)
def test_threats_reject_ambiguous_states(threats) -> None:
    payload = assessment_payload()
    payload["threats"] = threats
    with pytest.raises(InitialAssessmentValidationError):
        validate_initial_assessment(payload)


def test_outlier_requires_explicit_confirmation() -> None:
    payload = assessment_payload()
    payload["resources"]["water"] = {
        "status": "known",
        "amount": 100_001,
        "confirm_outlier": True,
        "rates": {"status": "unknown"},
    }
    assert validate_initial_assessment(payload)["resources"]["water"]["amount"] == 100_001


def test_all_unknown_persists_without_per_person_claims_or_phase_zero_tasks(
    tmp_path,
) -> None:
    db = Database(tmp_path / "assessment.db")
    manager = ResourceManager(db)
    manager.init_defaults()
    service = InitialAssessmentService(db, manager)
    assessment = validate_initial_assessment(unknown_assessment())

    tasks = service.apply(assessment)

    state = db.get_survivor_state()
    assert state["people_count"] == "unknown"
    assert state["people_count_status"] == "unknown"
    assert tasks == []
    assert db.get_active_tasks() == []
    for resource in manager.get_all_resources():
        assert resource.amount_known is False
        assert resource.people_count == 1
        assert resource.people_count_known is False
        assert resource.source == "user_input"
        assert resource.as_of


def test_apply_is_idempotent_and_does_not_replace_unrelated_tasks(tmp_path) -> None:
    db = Database(tmp_path / "idempotent.db")
    manager = ResourceManager(db)
    manager.init_defaults()
    service = InitialAssessmentService(db, manager)
    unrelated = Task(
        id="manual-existing",
        phase=3,
        priority=99,
        title="Keep me",
        status="in_progress",
        created_at="2026-01-01T00:00:00",
    )
    db.save_task(unrelated)
    assessment = validate_initial_assessment(unknown_assessment())

    service.apply(assessment)
    service.apply(assessment)

    rows = db.conn.execute("SELECT * FROM tasks").fetchall()
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids)) == 1
    saved = db.conn.execute(
        "SELECT * FROM tasks WHERE id='manual-existing'"
    ).fetchone()
    assert saved["status"] == "in_progress"
    assert saved["title"] == "Keep me"


def test_gap_plan_actions_render_in_both_languages(tmp_path) -> None:
    db = Database(tmp_path / "i18n.db")
    manager = ResourceManager(db)
    manager.init_defaults()
    service = SurvivalPlanService(db, manager)
    plan = service.generate(validate_initial_assessment(unknown_assessment()))
    original = "en"
    try:
        set_language("zh", persist=False)
        zh = service.payload(plan)["actions"][0]["title"]
        set_language("en", persist=False)
        en = service.payload(plan)["actions"][0]["title"]
    finally:
        set_language(original, persist=False)
    assert zh and en and zh != en
    assert not zh.startswith("assessment_gap_")
    assert not en.startswith("assessment_gap_")


def test_mixed_source_label_does_not_imply_older_data() -> None:
    original = get_language()
    try:
        set_language("zh", persist=False)
        assert render("t:resource_source_mixed") == "混合来源"
        set_language("en", persist=False)
        assert render("t:resource_source_mixed") == "Mixed sources"
    finally:
        set_language(original, persist=False)


def test_preview_separates_known_unknown_without_legacy_task_claims() -> None:
    payload = unknown_assessment()
    payload["resources"]["water"] = {
        "status": "known",
        "amount": 2,
        "rates": {"status": "unknown"},
    }
    normalized = validate_initial_assessment(payload)
    preview = assessment_preview(normalized)
    assert {item["domain"] for item in preview["known"]} >= {"water"}
    assert "water" not in preview["unknown"]
    assert "water_rate" in preview["unknown"]
    assert preview["actions"] == []


def test_resource_gap_task_aggregates_amount_and_rate_and_defers_low_risk(
    tmp_path,
) -> None:
    assessment = validate_initial_assessment(unknown_assessment())
    assert assessment_preview(assessment)["actions"] == []

    db = Database(tmp_path / "aggregate.db")
    manager = ResourceManager(db)
    manager.init_defaults()
    plan = SurvivalPlanService(db, manager).generate(assessment)
    water_plan_action = next(
        action for action in plan.actions if action.id == "survival-plan-gap-water"
    )
    assert {item["field"] for item in water_plan_action.evidence} >= {
        "water.amount",
        "water.consumption",
        "water.intake",
        "water.rate_basis",
    }
    assert db.get_active_tasks() == []

    rate_only = unknown_assessment()
    rate_only["resources"]["water"] = {
        "status": "known",
        "amount": 10,
        "rates": {"status": "unknown"},
    }
    rate_plan = SurvivalPlanService(db, manager).generate(
        validate_initial_assessment(rate_only)
    )
    rate_action = next(
        action
        for action in rate_plan.actions
        if action.id == "survival-plan-gap-water"
    )
    assert {item["field"] for item in rate_action.evidence} == {
        "water.consumption",
        "water.intake",
        "water.rate_basis",
    }

    all_known = assessment_payload()
    unknown_rate_plan = SurvivalPlanService(db, manager).generate(
        validate_initial_assessment(all_known)
    )
    assert any(
        action.id == "survival-plan-gap-water"
        for action in unknown_rate_plan.actions
    )
    for resource in all_known["resources"].values():
        resource["rates"] = {
            "status": "estimate",
            "basis": "group_total",
            "daily_consumption": 1,
            "daily_intake": 0,
        }
    complete_plan = SurvivalPlanService(db, manager).generate(
        validate_initial_assessment(all_known)
    )
    assert all(
        action.id != "survival-plan-gap-water"
        for action in complete_plan.actions
    )
    assert db.get_active_tasks() == []


def test_explicit_rate_estimate_requires_known_people_and_is_persisted(tmp_path) -> None:
    payload = assessment_payload()
    payload["resources"]["water"]["rates"] = {
        "status": "estimate",
        "basis": "group_total",
        "daily_consumption": 4,
        "daily_intake": 1,
    }
    assessment = validate_initial_assessment(payload)
    db = Database(tmp_path / "rate-estimate.db")
    manager = ResourceManager(db)
    manager.init_defaults()

    InitialAssessmentService(db, manager).apply(assessment)

    water = db.get_resource(ResourceType.WATER)
    assert water is not None
    assert water.source == "mixed"
    assert water.people_count == 2
    assert water.people_count_known is True
    assert water.consumption_known is True
    assert water.intake_known is True
    assert water.daily_consumption == 4
    assert water.daily_intake == 1
    assert water.estimated_remaining_hours == pytest.approx(80)
    assert "water_rate" not in assessment_preview(assessment)["unknown"]
    water_preview = next(
        item
        for item in assessment_preview(assessment)["resources"]
        if item["domain"] == "water"
    )
    assert water_preview["source"] == "mixed"
    assert water_preview["rate_status"] == "estimate"


def test_unknown_amount_with_explicit_rate_estimate_uses_estimate_source(tmp_path) -> None:
    payload = assessment_payload()
    payload["resources"]["water"] = {
        "status": "unknown",
        "rates": {
            "status": "estimate",
            "basis": "group_total",
            "daily_consumption": 4,
            "daily_intake": 1,
        },
    }
    assessment = validate_initial_assessment(payload)
    db = Database(tmp_path / "unknown-amount-estimate.db")
    manager = ResourceManager(db)
    manager.init_defaults()
    InitialAssessmentService(db, manager).apply(assessment)
    water = db.get_resource(ResourceType.WATER)
    assert water is not None
    assert water.amount_known is False
    assert water.consumption_known is True
    assert water.intake_known is True
    assert water.source == "estimate"


def test_group_total_rate_estimate_allows_unknown_people_without_per_person_default(
    tmp_path,
) -> None:
    payload = assessment_payload()
    payload["people_count"] = {"status": "unknown"}
    payload["resources"]["water"]["rates"] = {
        "status": "estimate",
        "basis": "group_total",
        "daily_consumption": 4,
        "daily_intake": 1,
    }
    assessment = validate_initial_assessment(payload)
    preview = assessment_preview(assessment)
    water_preview = next(
        item for item in preview["resources"] if item["domain"] == "water"
    )
    assert water_preview["rate_basis"] == "group_total"
    assert "water_rate" not in preview["unknown"]
    db = Database(tmp_path / "unknown-people-group-rate.db")
    manager = ResourceManager(db)
    manager.init_defaults()
    InitialAssessmentService(db, manager).apply(assessment)
    water = db.get_resource(ResourceType.WATER)
    assert water is not None
    assert water.rate_basis == "group_total"
    assert water.people_count_known is False


def test_rate_estimate_rejects_missing_or_per_person_basis() -> None:
    for basis in (None, "per_person"):
        payload = assessment_payload()
        payload["resources"]["water"]["rates"] = {
            "status": "estimate",
            "basis": basis,
            "daily_consumption": 4,
            "daily_intake": 1,
        }
        with pytest.raises(InitialAssessmentValidationError) as error:
            validate_initial_assessment(payload)
        assert any(item["code"] == "invalid_rate_basis" for item in error.value.errors)


def test_web_preview_is_read_only_and_complete_publishes_same_contract(tmp_path) -> None:
    client = TestClient(create_app(str(tmp_path / "web-assessment.db")))
    payload = unknown_assessment()

    preview = client.post(
        "/api/init/assessment/preview",
        json={"language": "en", "assessment": payload},
    )

    assert preview.status_code == 200, preview.text
    assert preview.json()["summary"]["as_of"]
    db = client.app.state.db
    assert db.is_initialized() is False
    assert db.get_survivor_state() == {}
    assert db.get_hardware_profile() == {}
    assert db.get_active_tasks() == []
    payload["as_of"] = preview.json()["summary"]["as_of"]

    plan = preview.json()["plan"]
    completed = client.post(
        "/api/init/complete",
        json={
            "language": "zh",
            "assessment": payload,
            "plan_id": plan["id"],
            "primary_action_id": plan["primary_candidate_ids"][0],
        },
    )

    assert completed.status_code == 200, completed.text
    assert completed.json()["created_task_ids"] == []
    assert db.is_initialized() is True
    assert db.get_survivor_state()["name"] == "幸存者"
    resources = client.get("/api/resources")
    assert resources.status_code == 200
    for resource in resources.json():
        assert resource["people_count_known"] is False
        assert resource["amount_per_person"] is None
        assert resource["remaining_hours_per_person"] is None


def test_web_returns_localized_structured_errors_without_any_draft(tmp_path) -> None:
    client = TestClient(create_app(str(tmp_path / "web-errors.db")))
    response = client.post(
        "/api/init/assessment/preview",
        json={"language": "zh", "assessment": {}},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "invalid_initial_assessment"
    assert body["errors"]
    assert all({"field", "code", "message"} <= set(error) for error in body["errors"])
    assert any("必须" in error["message"] for error in body["errors"])
    assert client.app.state.db.get_survivor_state() == {}
    assert client.app.state.db.get_hardware_profile() == {}


def test_web_template_exposes_bilingual_accessible_summary_contract(tmp_path) -> None:
    client = TestClient(create_app(str(tmp_path / "web-template.db")))
    html = client.get("/").text
    assert 'id="summary-resources"' in html
    assert "summary.resources.forEach" in html
    assert "web_init_rate_summary" in html
    assert "resource.source" in html
    assert "resource.rate_status" in html
    assert "resource.rate_basis==='group_total'" in html
    assert 'data-i18n="resource_unit_fire"' in html
    assert "renderHardwareSummary()" in html
    assert '<ol class="progress" aria-hidden="true">' in html
    assert 'id="people-count" type="number" min="1" max="10000" step="1" disabled' in html
    assert 'value="1" disabled' not in html
    assert "errorFocusTarget(error)" in html
    assert "document.title='ALLSPARK — '+tr('web_init_document_title')" in html
    assert 'aria-label="Initialization progress"' not in html
    assert 'aria-label="Language"' not in html
    assert 'aria-label="Amount status"' not in html
    assert 'aria-label="Rate status"' not in html


def test_first_run_copy_uses_natural_people_and_total_labels() -> None:
    previous = get_language()
    try:
        set_language("zh", persist=False)
        assert render("t:assessment_field_people_count") == "同行总人数（含自己）"
        assert render("t:init_assessment_daily_consumption") == "预计每日总消耗"
        assert render("t:web_init_group_total_basis") == "总量口径"
        assert render("t:web_init_step_situation") == "当前状况"
        assert render("t:web_init_step_resources") == "当前资源"
        assert render("t:web_init_step_summary") == "发布前核对"
        set_language("en", persist=False)
        assert render("t:assessment_field_people_count") == "People in your group (including you)"
        assert render("t:init_assessment_daily_consumption") == "Estimated total daily consumption"
        assert render("t:web_init_group_total_basis") == "total basis"
        assert render("t:web_init_step_situation") == "Current situation"
        assert render("t:web_init_step_resources") == "Current resources"
        assert render("t:web_init_step_summary") == "Review before publishing"
    finally:
        set_language(previous, persist=False)


def _assessment_candidate(db: Database) -> PreparedApplication:
    manager = ResourceManager(db)
    manager.init_defaults()
    container = ServiceContainer()
    container.register("initial_assessment", InitialAssessmentService(db, manager))
    container.register("survival_plan", SurvivalPlanService(db, manager))
    return PreparedApplication(
        bootstrap=SimpleNamespace(shutdown=MagicMock()),
        container=container,
        engine=MagicMock(),
    )


def test_web_assessment_drafts_converge_after_finalize_failure_and_changed_retry(
    monkeypatch, tmp_path
) -> None:
    client = TestClient(create_app(str(tmp_path / "assessment-retry.db")))
    db = client.app.state.db
    monkeypatch.setattr(
        web_ui_module,
        "_prepare_engine",
        lambda *args, **kwargs: _assessment_candidate(db),
    )
    original_finalize = db.finalize_initialization
    calls = 0

    def fail_once(language, plan_id=None, accepted_action_id=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("marker failed")
        return original_finalize(language, plan_id, accepted_action_id)

    monkeypatch.setattr(db, "finalize_initialization", fail_once)
    first_payload = unknown_assessment()
    first_preview = client.post(
        "/api/init/assessment/preview",
        json={"language": "en", "assessment": first_payload},
    ).json()
    first_payload["as_of"] = first_preview["summary"]["as_of"]
    first = client.post(
        "/api/init/complete",
        json={
            "language": "en",
            "assessment": first_payload,
            "plan_id": first_preview["plan"]["id"],
            "primary_action_id": first_preview["plan"]["primary_candidate_ids"][0],
        },
    )
    assert first.status_code == 503
    assert db.is_initialized() is False
    assert client.app.state.container is None
    assert db.get_active_tasks() == []
    assert db.get_survival_plan() is None

    complete = assessment_payload()
    for resource in complete["resources"].values():
        resource["rates"] = {
            "status": "estimate",
            "basis": "group_total",
            "daily_consumption": 1,
            "daily_intake": 0,
        }
    retry_preview = client.post(
        "/api/init/assessment/preview",
        json={"language": "en", "assessment": complete},
    ).json()
    complete["as_of"] = retry_preview["summary"]["as_of"]
    retry = client.post(
        "/api/init/complete",
        json={
            "language": "en",
            "assessment": complete,
            "plan_id": retry_preview["plan"]["id"],
            "primary_action_id": retry_preview["plan"]["primary_candidate_ids"][0],
        },
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["created_task_ids"] == []
    assert db.is_initialized() is True
    assert db.get_active_tasks() == []


def test_web_partial_plan_write_failure_retries_without_draft_leak(
    monkeypatch, tmp_path
) -> None:
    client = TestClient(create_app(str(tmp_path / "task-retry.db")))
    db = client.app.state.db
    monkeypatch.setattr(
        web_ui_module,
        "_prepare_engine",
        lambda *args, **kwargs: _assessment_candidate(db),
    )
    original_save = db.save_survival_plan
    calls = 0

    def fail_after_write_once(plan):
        nonlocal calls
        calls += 1
        original_save(plan)
        if calls == 1:
            raise RuntimeError("plan draft failed")

    monkeypatch.setattr(db, "save_survival_plan", fail_after_write_once)
    assessment = unknown_assessment()
    preview = client.post(
        "/api/init/assessment/preview",
        json={"language": "en", "assessment": assessment},
    ).json()
    assessment["as_of"] = preview["summary"]["as_of"]
    payload = {
        "language": "en",
        "assessment": assessment,
        "plan_id": preview["plan"]["id"],
        "primary_action_id": preview["plan"]["primary_candidate_ids"][0],
    }
    failed = client.post("/api/init/complete", json=payload)
    assert failed.status_code == 503
    assert db.is_initialized() is False
    assert db.get_survival_plan() is None

    retry = client.post("/api/init/complete", json=payload)
    assert retry.status_code == 200, retry.text
    assert db.get_active_tasks() == []
    assert db.get_survival_plan(active_only=True) is not None
