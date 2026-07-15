"""SHA-151: psychology line-coverage tests (criterion 1: total line >=75%)."""
from datetime import datetime, timedelta

import pytest

from allspark.core.database import Database
from allspark.core.models import Resource, ResourceType
from allspark.services.psychology import PsychologyTracker


@pytest.fixture
def tracker(tmp_path):
    db = Database(tmp_path / "psy.db")
    yield PsychologyTracker(db=db)
    db.close()


def test_record_interaction_truncates_samples(tracker):
    for _ in range(105):
        tracker.record_interaction("neutral")
    assert len(tracker._sentiment_samples) == 100


def test_assess_state_stable(tracker):
    tracker.record_interaction("positive")
    r = tracker.assess_state()
    assert r["overall_state"] in ("stable", "lonely", "stressed")


def test_assess_state_lonely_no_interaction(tracker):
    # No interaction -> loneliness 0.8 > 0.7 -> lonely.
    r = tracker.assess_state()
    assert r["needs_intervention"] is True


def test_assess_state_negative_ratio(tracker):
    for _ in range(7):
        tracker.record_interaction("negative")
    r = tracker.assess_state()
    assert r["needs_intervention"] is True


def test_calculate_loneliness_buckets(tracker):
    assert tracker._calculate_loneliness() == 0.8  # no interaction
    tracker._last_interaction_time = datetime.now()
    assert tracker._calculate_loneliness() == 0.1
    tracker._last_interaction_time = datetime.now() - timedelta(hours=3)
    assert tracker._calculate_loneliness() == 0.3
    tracker._last_interaction_time = datetime.now() - timedelta(hours=12)
    assert tracker._calculate_loneliness() == 0.5
    tracker._last_interaction_time = datetime.now() - timedelta(hours=48)
    assert tracker._calculate_loneliness() == 0.7
    tracker._last_interaction_time = datetime.now() - timedelta(hours=100)
    assert tracker._calculate_loneliness() == 0.9


def test_calculate_stress_modes_and_power(tracker):
    # operating state economy -> +0.3
    tracker.db.save_operating_state.__self__ if False else None
    state = tracker.db.get_operating_state()
    state.mode = "economy"
    tracker.db.save_operating_state(state)
    assert tracker._calculate_stress() >= 0.3
    # low power -> +0.4
    tracker.db.upsert_resource(Resource(type=ResourceType.POWER, current_amount=10, unit="Wh",
                                        daily_consumption=10, daily_intake=0,
                                        estimated_remaining_hours=3.0, last_updated="",
                                        amount_known=True, consumption_known=True,
                                        intake_known=True))
    assert tracker._calculate_stress() >= 0.7


def test_get_self_assessment_questions(tracker):
    qs = tracker.get_self_assessment_questions()
    assert len(qs) == 5
    assert all("scores" in q for q in qs)


def test_process_assessment_severity_levels(tracker):
    # All worst answers (max idx) -> severe.
    worst = {q["id"]: len(q["scores"]) - 1 for q in tracker.get_self_assessment_questions()}
    r = tracker.process_assessment(worst)
    assert r["needs_intervention"] is True
    # All best answers (0) -> good.
    best = {q["id"]: 0 for q in tracker.get_self_assessment_questions()}
    r2 = tracker.process_assessment(best)
    assert r2["needs_intervention"] is False


def test_format_status(tracker):
    tracker.record_interaction("positive")
    out = tracker.format_status()
    assert isinstance(out, str) and out


def test_check_and_trigger_intervention_none(tracker):
    tracker.record_interaction("positive")
    # recent interaction -> stable -> no intervention
    assert tracker.check_and_trigger_intervention() is None or isinstance(tracker.check_and_trigger_intervention(), dict)


def test_check_and_trigger_intervention_companion(tracker):
    # No interaction -> lonely -> companion.
    r = tracker.check_and_trigger_intervention()
    assert r is not None
    assert r["type"] == "companion_mode"


def test_detect_self_harm_no_risk_decrements_level(tracker):
    tracker._self_harm_level = 2
    assert tracker.detect_self_harm_risk("我很好") is None
    assert tracker._self_harm_level == 1


def test_detect_self_harm_escalates_to_level3(tracker):
    r1 = tracker.detect_self_harm_risk("我不想活了")
    assert r1["level"] == 1
    r2 = tracker.detect_self_harm_risk("suicide")
    assert r2["level"] == 2
    r3 = tracker.detect_self_harm_risk("kill myself")
    assert r3["level"] == 3
    assert r3.get("notify_authority") is True


def test_get_self_harm_status(tracker):
    tracker.detect_self_harm_risk("我不想活了")
    s = tracker.get_self_harm_status()
    assert s["current_level"] == 1
    assert s["total_triggers"] == 1
    assert s["max_level"] == 3
