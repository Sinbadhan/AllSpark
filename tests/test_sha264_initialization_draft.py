"""SHA-264: recoverable unpublished first-run drafts and atomic publish."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from allspark.adapters import web_ui as wui
from allspark.core.database import Database
from allspark.services.initial_assessment import (
    INITIALIZATION_DRAFT_MAX_BYTES,
    InitialAssessmentDraftValidationError,
    initialization_draft_progress,
    normalize_initialization_draft,
)
from allspark.services.resource_manager import ResourceManager
from tests.assessment_helpers import valid_initial_assessment
from tests.test_sha238_initial_assessment import _assessment_candidate


def _partial_payload() -> dict:
    return {
        "language": "en",
        "step": 2,
        "assessment": {
            "people_count": {"status": "known", "value": "2"},
            "health": {"status": "known", "value": "minor_injury"},
            "urgency": {"status": "unknown"},
            "shelter": {},
            "threats": {"status": "selected", "values": ["fire_risk"]},
            "resources": {
                "water": {
                    "status": "known",
                    "amount": "12",
                    "rates": {"status": "unknown"},
                }
            },
            "untrusted_extra": "must not persist",
        },
        "selected_primary_action_id": None,
        "untrusted_extra": {"token": "must not persist"},
    }


def _complete_payload(client: TestClient) -> dict:
    assessment = deepcopy(valid_initial_assessment())
    preview = client.post(
        "/api/init/assessment/preview",
        json={"language": "en", "assessment": assessment},
    )
    assert preview.status_code == 200, preview.text
    result = preview.json()
    assessment["as_of"] = result["summary"]["as_of"]
    assessment["confirmed"] = True
    return {
        "language": "en",
        "assessment": assessment,
        "plan_id": result["plan"]["id"],
        "primary_action_id": result["plan"]["primary_candidate_ids"][0],
    }


def test_partial_draft_is_whitelisted_bounded_and_reports_progress() -> None:
    normalized = normalize_initialization_draft(_partial_payload())
    progress = initialization_draft_progress(normalized)

    assert normalized["assessment"]["people_count"] == {
        "status": "known",
        "value": 2,
    }
    assert normalized["assessment"]["resources"]["water"]["amount"] == 12.0
    assert "untrusted_extra" not in normalized
    assert "untrusted_extra" not in normalized["assessment"]
    assert "people_count" in progress["completed"]
    assert "health" in progress["completed"]
    assert "shelter" in progress["missing"]
    assert "water" in progress["completed"]
    assert "water_rate" in progress["completed"]
    assert "food" in progress["missing"]

    oversized = {"language": "en", "blob": "x" * INITIALIZATION_DRAFT_MAX_BYTES}
    with pytest.raises(InitialAssessmentDraftValidationError) as exc:
        normalize_initialization_draft(oversized)
    assert (exc.value.field, exc.value.code) == ("draft", "too_large")


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda payload: None, ("draft", "object_required")),
        (lambda payload: {**payload, "language": "fr"}, ("language", "invalid_choice")),
        (lambda payload: {**payload, "step": True}, ("step", "invalid_choice")),
        (
            lambda payload: {**payload, "assessment": []},
            ("assessment", "object_required"),
        ),
        (
            lambda payload: {
                **payload,
                "assessment": {**payload["assessment"], "resources": []},
            },
            ("resources", "object_required"),
        ),
        (
            lambda payload: {**payload, "selected_primary_action_id": ""},
            ("selected_primary_action_id", "invalid_choice"),
        ),
        (
            lambda payload: {
                **payload,
                "assessment": {
                    **payload["assessment"],
                    "people_count": {"status": "known", "value": 0},
                },
            },
            ("people_count", "people_range"),
        ),
        (
            lambda payload: {
                **payload,
                "assessment": {
                    **payload["assessment"],
                    "health": {"status": "known", "value": "not_a_condition"},
                },
            },
            ("health", "invalid_choice"),
        ),
        (
            lambda payload: {
                **payload,
                "assessment": {
                    **payload["assessment"],
                    "threats": {"status": "selected", "values": "fire_risk"},
                },
            },
            ("threats", "invalid_choice"),
        ),
        (
            lambda payload: {
                **payload,
                "assessment": {
                    **payload["assessment"],
                    "threats": {"status": "selected", "values": ["fictional"]},
                },
            },
            ("threats", "invalid_choice"),
        ),
        (
            lambda payload: {
                **payload,
                "assessment": {
                    **payload["assessment"],
                    "resources": {
                        "water": {
                            "status": "known",
                            "amount": 12,
                            "confirm_outlier": "yes",
                        }
                    },
                },
            },
            ("resources.water.confirm_outlier", "not_boolean"),
        ),
        (
            lambda payload: {
                **payload,
                "assessment": {
                    **payload["assessment"],
                    "resources": {"water": {"status": "known", "amount": -1}},
                },
            },
            ("resources.water.amount", "negative"),
        ),
        (
            lambda payload: {
                **payload,
                "assessment": {
                    **payload["assessment"],
                    "resources": {
                        "water": {
                            "status": "known",
                            "amount": 12,
                            "rates": {
                                "status": "estimate",
                                "daily_consumption": -1,
                            },
                        }
                    },
                },
            },
            ("resources.water.rates.daily_consumption", "negative"),
        ),
    ],
)
def test_draft_normalization_rejects_malformed_or_unsafe_fields(mutate, expected) -> None:
    with pytest.raises(InitialAssessmentDraftValidationError) as exc:
        normalize_initialization_draft(mutate(_partial_payload()))
    assert (exc.value.field, exc.value.code) == expected


def test_resource_snapshot_accepts_naive_current_time_without_crashing() -> None:
    resource = SimpleNamespace(as_of=(datetime.now() - timedelta(minutes=1)).isoformat())

    assert ResourceManager.is_snapshot_current(resource, now=datetime.now()) is True


def test_database_revision_conflict_and_discard_preserve_published_rows(tmp_path) -> None:
    db = Database(tmp_path / "draft.db")
    try:
        db.save_survivor_state("published", "keep")
        first = db.save_initialization_draft(
            normalize_initialization_draft(_partial_payload()),
            source="web",
            expected_revision=0,
        )
        assert first["revision"] == 1
        with pytest.raises(ValueError, match="revision conflict"):
            db.save_initialization_draft(first["payload"], source="web", expected_revision=0)
        db.delete_initialization_draft()
        assert db.get_initialization_draft() is None
        assert db.get_survivor_state() == {"published": "keep"}
    finally:
        db.close()


def test_committed_draft_survives_abrupt_process_exit(tmp_path) -> None:
    db_path = tmp_path / "power-loss.db"
    script = """
import os
from allspark.core.database import Database
db = Database(r'{path}')
db.save_initialization_draft({{'language':'en','step':2,'assessment':{{}},'selected_primary_action_id':None}}, source='web', expected_revision=0)
os._exit(0)
""".format(path=db_path)
    subprocess.run([sys.executable, "-c", script], check=True, cwd=Path.cwd())

    reopened = Database(db_path)
    try:
        draft = reopened.get_initialization_draft()
        assert draft is not None
        assert draft["revision"] == 1
        assert draft["payload"]["language"] == "en"
        assert stat.S_IMODE(os.stat(db_path).st_mode) == 0o600
    finally:
        reopened.close()


def test_web_draft_survives_app_restart_and_discard_is_explicit(tmp_path) -> None:
    db_path = tmp_path / "web-restart.db"
    first = TestClient(wui.create_app(str(db_path)))
    saved = first.post("/api/init/draft", json={"revision": 0, "payload": _partial_payload()})
    assert saved.status_code == 200, saved.text
    assert saved.json()["status"] == "unpublished"
    assert first.app.state.db.get_survivor_state() == {}
    first.close()
    first.app.state.db.close()

    second = TestClient(wui.create_app(str(db_path)))
    restored = second.get("/api/init/draft")
    assert restored.status_code == 200
    assert restored.json()["revision"] == 1
    assert restored.json()["payload"]["assessment"]["health"]["value"] == ("minor_injury")
    assert second.delete("/api/init/draft").json()["status"] == "discarded"
    assert second.get("/api/init/draft").json() == {"status": "empty"}
    assert second.app.state.db.get_survivor_state() == {}
    second.close()


def test_stale_browser_revision_cannot_overwrite_newer_draft(tmp_path) -> None:
    client = TestClient(wui.create_app(str(tmp_path / "revision.db")))
    first = client.post("/api/init/draft", json={"revision": 0, "payload": _partial_payload()})
    stale = client.post("/api/init/draft", json={"revision": 0, "payload": _partial_payload()})

    assert first.status_code == 200
    assert stale.status_code == 409
    assert stale.json()["error"] == "draft_revision_conflict"
    assert client.get("/api/init/draft").json()["revision"] == 1


def test_draft_mutations_cannot_race_initialization_publish(tmp_path) -> None:
    client = TestClient(wui.create_app(str(tmp_path / "draft-lock.db")))
    lock = client.app.state.init_lock
    assert lock.acquire(blocking=False) is True
    try:
        save = client.post("/api/init/draft", json={"revision": 0, "payload": _partial_payload()})
        discard = client.delete("/api/init/draft")
    finally:
        lock.release()

    assert save.status_code == 409
    assert save.json()["error"] == "bootstrap_in_progress"
    assert discard.status_code == 409
    assert discard.json()["error"] == "bootstrap_in_progress"
    assert client.get("/api/init/draft").json() == {"status": "empty"}


def test_web_draft_rejects_malformed_requests_and_closed_bootstrap(tmp_path) -> None:
    client = TestClient(wui.create_app(str(tmp_path / "draft-validation.db")))

    malformed_json = client.post("/api/init/draft", content=b"{", headers={"content-type": "application/json"})
    invalid_revision = client.post("/api/init/draft", json={"revision": True, "payload": _partial_payload()})
    invalid_payload = client.post(
        "/api/init/draft",
        json={"revision": 0, "payload": {**_partial_payload(), "language": "fr"}},
    )

    assert malformed_json.status_code == 422
    assert malformed_json.json()["error"] == "invalid_draft"
    assert invalid_revision.status_code == 422
    assert invalid_revision.json()["error"] == "invalid_draft_revision"
    assert invalid_payload.status_code == 422
    assert invalid_payload.json()["errors"] == [{"field": "language", "code": "invalid_choice"}]

    client.app.state.initialized = True
    assert client.post("/api/init/draft", json={"revision": 0, "payload": _partial_payload()}).status_code == 410
    assert client.delete("/api/init/draft").status_code == 410


def test_failed_publish_rolls_back_facts_and_keeps_recoverable_draft(monkeypatch, tmp_path) -> None:
    client = TestClient(wui.create_app(str(tmp_path / "atomic.db")))
    db = client.app.state.db
    monkeypatch.setattr(wui, "_prepare_engine", lambda *args, **kwargs: _assessment_candidate(db))
    draft = client.post("/api/init/draft", json={"revision": 0, "payload": _partial_payload()})
    assert draft.status_code == 200
    payload = _complete_payload(client)
    ResourceManager(db).init_defaults()
    before_resources = [resource.__dict__.copy() for resource in db.get_all_resources()]
    db.conn.execute(
        """CREATE TRIGGER reject_survivor_publish
           BEFORE INSERT ON survivor_state
           BEGIN SELECT RAISE(ABORT, 'publish failed'); END"""
    )
    db.conn.commit()

    failed = client.post("/api/init/complete", json=payload)

    assert failed.status_code == 503
    assert db.is_initialized() is False
    assert db.get_survivor_state() == {}
    assert db.get_hardware_profile() == {}
    assert [resource.__dict__ for resource in db.get_all_resources()] == before_resources
    assert db.get_survival_plan() is None
    assert db.get_initialization_draft() is not None
    assert client.app.state.container is None

    db.conn.execute("DROP TRIGGER reject_survivor_publish")
    db.conn.commit()
    retry = client.post("/api/init/complete", json=payload)
    assert retry.status_code == 200, retry.text
    assert db.is_initialized() is True
    assert db.get_initialization_draft() is None
    plan_count = db.conn.execute("SELECT COUNT(*) AS count FROM survival_plans").fetchone()
    assert plan_count["count"] == 1


def test_init_template_has_server_recovery_without_browser_storage() -> None:
    template = Path("allspark/templates/init.html").read_text(encoding="utf-8")
    assert 'id="draft-recovery"' in template
    assert 'data-action="draft-continue"' in template
    assert 'data-action="draft-discard-confirm"' in template
    assert 'aria-controls="draft-confirm"' in template
    assert 'class="btn btn-danger"' in template
    assert "/api/init/draft" in template
    assert "localStorage" not in template
    assert "sessionStorage" not in template
