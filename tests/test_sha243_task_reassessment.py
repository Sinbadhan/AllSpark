"""SHA-243: traceable task outcomes, reassessment, and dashboard truth."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from allspark.adapters.web_ui import create_app
from allspark.commands.knowledge import TaskCommand
from allspark.core.database import Database
from allspark.core.i18n import get_language, set_language
from allspark.core.models import ResourceType
from tests.test_sha196_browser import _Chrome, _chrome_binary, _serve


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


def _seed_plan_and_task(client: TestClient):
    container = client.app.state.container
    db = client.app.state.db
    resource_manager = container.get("resource_manager")
    resource_manager.update_resource(
        ResourceType.WATER,
        10,
        consumption=2,
        intake=0,
        rate_basis="group_total",
        source="user_input",
        people_count=2,
        people_count_known=True,
        as_of=datetime.now(timezone.utc).isoformat(),
        amount_known=True,
        consumption_known=True,
        intake_known=True,
    )
    plan_service = container.get("survival_plan")
    plan = plan_service.generate_current()
    selected = plan_service.primary_candidate_ids(plan)[0]
    db.replace_active_survival_plan(plan, accepted_action_id=selected)
    task, _ = container.get("mission_planner").create_task(
        title="Check water result",
        source="manual",
    )
    return task, plan


def test_terminal_outcome_requires_result_and_existing_task(tmp_path: Path) -> None:
    client = _client(tmp_path / "required.db")
    task, _ = _seed_plan_and_task(client)

    missing = client.post(f"/api/tasks/{task.id}/complete", json={})
    assert missing.status_code == 422
    assert missing.json()["errors"] == [{"field": "result", "code": "required"}]
    assert client.app.state.db.get_task(task.id).status == "pending"

    unknown = client.post(
        "/api/tasks/not-real/fail", json={"result": "Could not reach it"}
    )
    assert unknown.status_code == 404


def test_resource_change_requires_explicit_confirmation_without_partial_write(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path / "confirmation.db")
    task, plan = _seed_plan_and_task(client)

    response = client.post(
        f"/api/tasks/{task.id}/complete",
        json={
            "result": "Counted the remaining water",
            "evidence": ["Marked bottle levels"],
            "resource_update": {"type": "water", "amount": 8},
            "confirm_resource_update": False,
        },
    )
    assert response.status_code == 409
    assert response.json()["errors"] == [
        {"field": "confirm_resource_update", "code": "confirmation_required"}
    ]
    water = client.app.state.db.get_resource(ResourceType.WATER)
    assert water is not None and water.current_amount == 10
    assert client.app.state.db.get_task(task.id).status == "pending"
    assert client.app.state.db.get_survival_plan(active_only=True).id == plan.id


def test_confirmed_outcome_updates_resource_reassesses_and_records_history(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path / "outcome.db")
    task, old_plan = _seed_plan_and_task(client)

    response = client.post(
        f"/api/tasks/{task.id}/complete",
        json={
            "result": "Counted the remaining water",
            "evidence": ["Marked bottle levels", "Second person checked"],
            "resource_update": {"type": "water", "amount": 8},
            "confirm_resource_update": True,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["new_status"] == "completed"
    assert payload["resource_changed"] is True
    assert payload["plan_changed"] is True
    assert payload["plan"]["id"] != old_plan.id
    assert payload["next_task"] is not None

    saved = client.app.state.db.get_task(task.id)
    assert saved is not None
    assert saved.status == "completed"
    assert saved.result == "Counted the remaining water"
    assert saved.evidence == ["Marked bottle levels", "Second person checked"]
    assert saved.completed_at
    water = client.app.state.db.get_resource(ResourceType.WATER)
    assert water is not None and water.current_amount == 8
    assert water.daily_consumption == 2
    assert water.daily_intake == 0
    assert client.get("/api/tasks").json()
    history = client.get("/api/tasks?include_terminal=true").json()
    assert any(item["id"] == task.id and item["result"] for item in history)


def test_failed_and_skipped_outcomes_are_traceable_and_not_reusable(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path / "terminal.db")
    task, _ = _seed_plan_and_task(client)

    failed = client.post(
        f"/api/tasks/{task.id}/fail",
        json={"result": "Route blocked", "evidence": ["Collapsed bridge"]},
    )
    assert failed.status_code == 200
    assert failed.json()["task"]["status"] == "failed"
    repeat = client.post(
        f"/api/tasks/{task.id}/skip", json={"result": "No longer relevant"}
    )
    assert repeat.status_code == 409

    next_task, _ = client.app.state.container.get("mission_planner").create_task(
        title="Optional check", source="manual"
    )
    skipped = client.post(
        f"/api/tasks/{next_task.id}/skip",
        json={"result": "Deferred for a safer window"},
    )
    assert skipped.status_code == 200
    assert skipped.json()["task"]["status"] == "skipped"


def test_active_plan_can_be_tracked_idempotently(tmp_path: Path) -> None:
    client = _client(tmp_path / "plan-task.db")
    _seed_plan_and_task(client)

    first = client.post("/api/tasks/from-plan")
    second = client.post("/api/tasks/from-plan")
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["task"]["id"] == second.json()["task"]["id"]
    assert first.json()["task"]["source"] == "survival_plan"


def test_status_counts_configured_resources_and_keeps_unknown_mode_truthful(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path / "status.db")
    status = client.get("/api/status").json()
    assert len(status["resources"]) == 5
    assert status["configured_resource_count"] == 0
    assert status["mode"] is None
    assert status["mode_status"] == "unknown"
    assert all(item["risk_status"] == "unknown" for item in status["resources"])


def test_resource_risk_uses_type_specific_thresholds_not_168_hour_scale(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path / "risk.db")
    manager = client.app.state.container.get("resource_manager")
    now = datetime.now(timezone.utc).isoformat()
    manager.update_resource(
        ResourceType.WATER,
        2,
        consumption=4,
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
    manager.update_resource(
        ResourceType.STORAGE,
        8,
        source="user_input",
        people_count=1,
        people_count_known=True,
        as_of=now,
        amount_known=True,
        consumption_known=False,
        intake_known=False,
        capacity=100,
        capacity_known=True,
    )
    resources = {item["type"]: item for item in client.get("/api/resources").json()}
    assert resources["water"]["risk_status"] == "critical"
    assert resources["storage"]["risk_status"] == "warning"


def test_reassessment_failure_restores_task_resource_and_active_plan(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path / "rollback.db")
    task, old_plan = _seed_plan_and_task(client)
    service = client.app.state.container.get("task_outcome")

    with patch.object(service.survival_plan, "generate_current", side_effect=RuntimeError("boom")):
        try:
            service.record(
                task.id,
                status="completed",
                result="Measured water",
                resource_update={"type": "water", "amount": 8},
                confirm_resource_update=True,
            )
        except RuntimeError as exc:
            assert str(exc) == "boom"
        else:
            raise AssertionError("reassessment failure should propagate")

    restored_task = client.app.state.db.get_task(task.id)
    restored_water = client.app.state.db.get_resource(ResourceType.WATER)
    restored_plan = client.app.state.db.get_survival_plan(active_only=True)
    assert restored_task is not None and restored_task.status == "pending"
    assert restored_task.result == "" and restored_task.completed_at == ""
    assert restored_water is not None and restored_water.current_amount == 10
    assert restored_plan is not None and restored_plan.id == old_plan.id


def test_next_task_failure_rolls_back_the_whole_outcome_transaction(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path / "atomic-rollback.db")
    task, old_plan = _seed_plan_and_task(client)
    service = client.app.state.container.get("task_outcome")

    with patch.object(
        service.mission_planner,
        "create_task_from_active_plan",
        side_effect=RuntimeError("task write interrupted"),
    ):
        with pytest.raises(RuntimeError, match="task write interrupted"):
            service.record(
                task.id,
                status="completed",
                result="Measured water",
                resource_update={"type": "water", "amount": 8},
                confirm_resource_update=True,
            )

    restored_task = client.app.state.db.get_task(task.id)
    restored_water = client.app.state.db.get_resource(ResourceType.WATER)
    restored_plan = client.app.state.db.get_survival_plan(active_only=True)
    assert restored_task is not None and restored_task.status == "pending"
    assert restored_water is not None and restored_water.current_amount == 10
    assert restored_plan is not None and restored_plan.id == old_plan.id


def test_timeline_failure_does_not_turn_a_saved_outcome_into_an_api_failure(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path / "timeline-failure.db")
    task, _ = _seed_plan_and_task(client)
    service = client.app.state.container.get("task_outcome")
    timeline = service.timeline_provider()

    with patch.object(
        timeline, "record_system_event", side_effect=RuntimeError("timeline unavailable")
    ):
        response = client.post(
            f"/api/tasks/{task.id}/complete",
            json={"result": "Measured and confirmed"},
        )

    assert response.status_code == 200
    assert response.json()["task"]["status"] == "completed"
    assert client.app.state.db.get_task(task.id).result == "Measured and confirmed"


def test_cli_can_record_evidence_confirm_resource_and_report_reassessment(
    tmp_path: Path,
) -> None:
    set_language("en", persist=False)
    client = _client(tmp_path / "cli-outcome.db")
    task, _ = _seed_plan_and_task(client)
    command = TaskCommand(client.app.state.container)
    command.console = MagicMock()

    command.execute(
        [
            "done",
            task.id,
            "Counted",
            "remaining",
            "water",
            "--evidence",
            "Bottle",
            "marks",
            "checked",
            "--resource",
            "water",
            "8",
            "--confirm-resource",
        ]
    )

    saved = client.app.state.db.get_task(task.id)
    water = client.app.state.db.get_resource(ResourceType.WATER)
    output = "\n".join(str(call.args[0]) for call in command.console.print.call_args_list)
    assert saved is not None and saved.status == "completed"
    assert saved.result == "Counted remaining water"
    assert saved.evidence == ["Bottle marks checked"]
    assert water is not None and water.current_amount == 8
    assert "24-hour" in output and "Next tracked action" in output


def test_cli_unconfirmed_resource_outcome_is_read_only(tmp_path: Path) -> None:
    set_language("en", persist=False)
    client = _client(tmp_path / "cli-unconfirmed.db")
    task, old_plan = _seed_plan_and_task(client)
    command = TaskCommand(client.app.state.container)
    command.console = MagicMock()

    command.execute(
        ["done", task.id, "Counted", "water", "--resource", "water", "8"]
    )

    saved = client.app.state.db.get_task(task.id)
    water = client.app.state.db.get_resource(ResourceType.WATER)
    active_plan = client.app.state.db.get_survival_plan(active_only=True)
    assert saved is not None and saved.status == "pending"
    assert water is not None and water.current_amount == 10
    assert active_plan is not None and active_plan.id == old_plan.id
    assert "Confirm" in str(command.console.print.call_args.args[0])


def test_templates_expose_accessible_outcome_flow_without_fake_resource_scale() -> None:
    root = Path(__file__).parents[1] / "allspark" / "templates"
    executions = (root / "executions.html").read_text()
    dashboard = (root / "index.html").read_text()
    footer = (root / "base.html").read_text()

    assert 'role="dialog" aria-modal="true"' in executions
    assert 'id="task-outcome-result"' in executions
    assert 'id="task-outcome-resource-confirm"' in executions
    assert 'data-task-action="skip"' in executions
    assert 'event.key === "Escape"' in executions
    assert 'I18N["web_task_source_" + (t.source || "unknown")]' in executions
    assert "schedule:" in footer
    assert "(r.remaining_hours / 168)" not in dashboard
    assert "r.risk_status" in dashboard
    assert "configured_resource_count" in footer


@pytest.mark.parametrize("language", ["zh", "en"])
def test_real_chrome_task_outcome_is_keyboard_ready_and_mobile_contained(
    tmp_path: Path, language: str
) -> None:
    client = _client(tmp_path / f"chrome-{language}.db")
    client.post("/api/system/language", json={"language": language})
    task, _ = _seed_plan_and_task(client)

    with _serve(client.app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / f"chrome-profile-{language}"
    ) as browser:
        browser.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 320, "height": 568, "deviceScaleFactor": 1, "mobile": True},
        )
        browser.navigate(base_url + "/executions")
        browser.wait_for(
            f'Boolean(document.querySelector("[data-task-id=\\"{task.id}\\"][data-task-action=\\"complete\\"]"))'
        )
        pending_icon = browser.evaluate(
            f'document.querySelector("[data-task-id=\\"{task.id}\\"]")?.closest("[data-exec-action=\\"toggle-detail\\"]")?.querySelector(".material-symbols-outlined")?.textContent || ""'
        )
        assert pending_icon == "◷"
        browser.evaluate(
            f'document.querySelector("[data-task-id=\\"{task.id}\\"][data-task-action=\\"complete\\"]").click()'
        )
        browser.wait_for(
            'document.getElementById("task-outcome-modal").style.display === "flex"'
        )
        modal_state = browser.evaluate(
            """(() => {
              const modal = document.getElementById('task-outcome-modal');
              const dialog = modal.querySelector('[role="dialog"]');
              const rect = dialog.getBoundingClientRect();
              return {
                focused: document.activeElement?.id,
                labelledBy: dialog.getAttribute('aria-labelledby'),
                pageFits: document.documentElement.scrollWidth <= innerWidth + 1,
                dialogFits: rect.left >= 0 && rect.right <= innerWidth && rect.bottom <= innerHeight,
                resultRequired: document.getElementById('task-outcome-result').required,
                resourceDisabled: document.getElementById('task-outcome-resource-fields').disabled,
              };
            })()"""
        )
        assert modal_state == {
            "focused": "task-outcome-result",
            "labelledBy": "task-outcome-title",
            "pageFits": True,
            "dialogFits": True,
            "resultRequired": True,
            "resourceDisabled": True,
        }

        browser.evaluate(
            "document.getElementById('task-outcome-modal').dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))"
        )
        browser.wait_for(
            'document.getElementById("task-outcome-modal").style.display === "none"'
        )
        restored = browser.evaluate(
            "document.activeElement?.dataset?.taskAction || ''"
        )
        assert restored == "complete"
        browser.evaluate(
            f'document.querySelector("[data-task-id=\\"{task.id}\\"][data-task-action=\\"complete\\"]").click()'
        )
        browser.wait_for(
            'document.getElementById("task-outcome-modal").style.display === "flex"'
        )

        browser.evaluate(
            """(() => {
              document.getElementById('task-outcome-result').value = 'Observed result';
              document.getElementById('task-outcome-evidence').value = 'Measured twice';
              document.getElementById('task-outcome-form').requestSubmit();
            })()"""
        )
        browser.wait_for(
            'document.getElementById("stat-success").textContent === "1"'
        )
        browser.wait_for(
            'document.getElementById("task-outcome-modal").style.display === "none"'
        )
        completed = browser.evaluate(
            f"""(() => {{
              const row = Array.from(document.querySelectorAll('#exec-list > div'))
                .find(item => item.textContent.includes('Observed result'));
              row?.querySelector('[data-exec-action="toggle-detail"]')?.click();
              return {{
                found: Boolean(row),
                pageFits: document.documentElement.scrollWidth <= innerWidth + 1,
                savedResult: row?.textContent.includes('Observed result') || false,
                sourceLabel: row?.textContent.includes({"'手动创建'" if language == "zh" else "'Manual'"}) || false,
                sourceEnumLeaked: row?.textContent.includes('manual') || false,
                terminalButtons: document.querySelectorAll('[data-task-id="{task.id}"][data-exec-action="task-outcome"]').length,
              }};
            }})()"""
        )
        assert completed == {
            "found": True,
            "pageFits": True,
            "savedResult": True,
            "sourceLabel": True,
            "sourceEnumLeaked": False,
            "terminalButtons": 0,
        }
