"""Tests for WarningProtocol — PRD §3.1.3 资源预警协议闭环"""

import pytest

from allspark.core.database import Database
from allspark.core.models import Resource, ResourceType
from allspark.services.warning_protocol import WarningProtocol


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "test.db"))


@pytest.fixture
def protocol(db):
    return WarningProtocol(db)


# ─── Step ②: Evaluate Solutions ─────────────────────────────────────────────


class TestEvaluateSolutions:
    def test_water_warning_returns_plans(self, protocol, db):
        # Setup: add water resource with low remaining
        db.upsert_resource(Resource(
            type=ResourceType.WATER, current_amount=5, unit="L",
            daily_consumption=3, daily_intake=0, estimated_remaining_hours=40,
        ))
        warning = {"resource": "water", "level": "critical", "message": "Water < 3 days"}
        plans = protocol.evaluate_solutions(warning)
        assert len(plans) > 0
        assert any("water" in p.title.lower() or "水" in p.title for p in plans)

    def test_unknown_resource_returns_empty(self, protocol, db):
        warning = {"resource": "unknown_resource", "level": "warning"}
        plans = protocol.evaluate_solutions(warning)
        # Fallback should not have unknown resource
        assert isinstance(plans, list)

    def test_fallback_solutions_used_when_no_knowledge(self, protocol, db):
        warning = {"resource": "power", "level": "critical", "message": "Power < 6h"}
        plans = protocol.evaluate_solutions(warning)
        assert len(plans) > 0
        assert all(p.solution_source == "fallback" for p in plans)

    def test_plans_have_steps(self, protocol, db):
        warning = {"resource": "food", "level": "warning", "message": "Food < 5 days"}
        plans = protocol.evaluate_solutions(warning)
        for plan in plans:
            assert len(plan.steps) > 0


# ─── Step ③: Rank Action Plans ──────────────────────────────────────────────


class TestRankActionPlans:
    def test_plans_sorted_by_score(self, protocol, db):
        from allspark.core.models import ActionPlan
        plans = [
            ActionPlan(id="p1", warning_id="water", resource_type="water",
                       solution_source="fallback", steps=["a"], rank_score=0.5,
                       title="Plan A"),
            ActionPlan(id="p2", warning_id="water", resource_type="water",
                       solution_source="fallback", steps=["b", "c"], rank_score=0.9,
                       title="Plan B"),
        ]
        ranked = protocol.rank_action_plans(plans)
        assert ranked[0].title == "Plan B"
        assert ranked[1].title == "Plan A"

    def test_rank_without_calculator_uses_step_count(self, protocol, db):
        from allspark.core.models import ActionPlan
        plans = [
            ActionPlan(id="p1", warning_id="water", resource_type="water",
                       solution_source="fallback", steps=["a", "b", "c"], rank_score=0.0,
                       title="Many steps"),
            ActionPlan(id="p2", warning_id="water", resource_type="water",
                       solution_source="fallback", steps=["x"], rank_score=0.0,
                       title="One step"),
        ]
        ranked = protocol.rank_action_plans(plans)
        # Fewer steps = higher score
        assert ranked[0].title == "One step"


# ─── Step ④: Notify by Personality ──────────────────────────────────────────


class TestNotifyByPersonality:
    def test_crisis_mode_shows_only_top_plan(self, protocol, db):
        from allspark.core.models import ActionPlan
        plans = [
            ActionPlan(id="p1", warning_id="water", resource_type="water",
                       solution_source="fallback", steps=["a"], rank_score=0.9,
                       title="Best plan"),
            ActionPlan(id="p2", warning_id="water", resource_type="water",
                       solution_source="fallback", steps=["b"], rank_score=0.5,
                       title="OK plan"),
        ]
        warning = {"resource": "water", "level": "critical", "message": "Water critical"}
        notification = protocol.notify_by_personality(warning, plans)
        assert "Best plan" in notification
        # In crisis mode, second plan should NOT appear
        assert "OK plan" not in notification

    def test_stable_mode_shows_top_3_plans(self, protocol, db):
        from allspark.core.models import ActionPlan
        plans = [
            ActionPlan(id="p1", warning_id="water", resource_type="water",
                       solution_source="fallback", steps=["a"], rank_score=0.9,
                       title="Plan A"),
            ActionPlan(id="p2", warning_id="water", resource_type="water",
                       solution_source="fallback", steps=["b"], rank_score=0.5,
                       title="Plan B"),
            ActionPlan(id="p3", warning_id="water", resource_type="water",
                       solution_source="fallback", steps=["c"], rank_score=0.3,
                       title="Plan C"),
        ]
        warning = {"resource": "water", "level": "warning", "message": "Water low"}
        notification = protocol.notify_by_personality(warning, plans)
        assert "Plan A" in notification
        assert "Plan B" in notification
        assert "Plan C" in notification


# ─── Step ⑤: Track Execution ───────────────────────────────────────────────


class TestTrackExecution:
    def test_track_updates_status(self, protocol, db):
        from allspark.core.models import ActionPlan
        plan = ActionPlan(
            id="plan-test1", warning_id="water", resource_type="water",
            solution_source="fallback", steps=["step1"], title="Test plan",
        )
        db.save_action_plan(plan)

        result = protocol.track_execution("plan-test1", "executing", "started")
        assert result is True

        updated = db.get_action_plan("plan-test1")
        assert updated.status == "executing"
        assert updated.result == "started"

    def test_track_nonexistent_plan(self, protocol, db):
        result = protocol.track_execution("nonexistent", "executing")
        assert result is False


# ─── Step ⑥: Re-evaluate if Failed ────────────────────────────────────────


class TestReEvaluate:
    def test_reevaluate_excludes_failed(self, protocol, db):
        from allspark.core.models import ActionPlan
        plan = ActionPlan(
            id="plan-fail1", warning_id="water", resource_type="water",
            solution_source="fallback", steps=["step1"],
            title="Collect water",
            status="failed",
        )
        db.save_action_plan(plan)

        alternatives = protocol.re_evaluate_if_failed("plan-fail1")
        # Should get alternative plans, not the same one
        for alt in alternatives:
            assert alt.title != plan.title

    def test_reevaluate_nonexistent_returns_empty(self, protocol, db):
        result = protocol.re_evaluate_if_failed("nonexistent")
        assert result == []


# ─── Full Pipeline ──────────────────────────────────────────────────────────


class TestProcessWarning:
    def test_full_pipeline(self, protocol, db):
        db.upsert_resource(Resource(
            type=ResourceType.WATER, current_amount=3, unit="L",
            daily_consumption=2, daily_intake=0, estimated_remaining_hours=36,
        ))
        warning = {"resource": "water", "level": "critical", "message": "Water < 3 days"}
        result = protocol.process_warning(warning)

        assert result["plan_count"] > 0
        assert result["notification"] is not None
        assert result["top_plan"] is not None

    def test_pipeline_saves_plans_to_db(self, protocol, db):
        warning = {"resource": "food", "level": "warning", "message": "Food < 5 days"}
        protocol.process_warning(warning)

        # Plans should be saved in DB
        plans = db.get_action_plans_by_warning("food")
        assert len(plans) > 0
