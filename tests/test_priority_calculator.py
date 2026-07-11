"""Tests for PriorityCalculator — PRD §10.4 多维度优先级算法"""


import pytest

from allspark.core.database import Database
from allspark.core.models import Goal, Task
from allspark.services.priority_calculator import PriorityCalculator


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "test.db"))


@pytest.fixture
def calc(db):
    return PriorityCalculator(db)


# ─── Score Calculation ───────────────────────────────────────────────────────


class TestCalculate:
    def test_survival_goal_high_score(self, calc, db):
        goal = Goal(
            id="water-abc", title="找到安全水源", description="寻找并净化水源",
            category="survival", priority="critical", status="active",
        )
        score = calc.calculate(goal)
        assert 0.5 <= score <= 1.0

    def test_civilization_goal_lower_score(self, calc, db):
        goal = Goal(
            id="comm-abc", title="建立通信网络", description="远距离通信",
            category="civilization", priority="low", status="active",
        )
        score = calc.calculate(goal)
        assert score < 0.7

    def test_context_overrides(self, calc, db):
        goal = Goal(id="test-1", title="Test", category="survival", status="active")
        high = calc.calculate(goal, {"urgency": 1.0, "impact": 1.0})
        low = calc.calculate(goal, {"urgency": 0.0, "impact": 0.0})
        assert high > low

    def test_skill_matching_feasibility(self, calc, db):
        goal = Goal(
            id="water-1", title="水净化", description="净化饮用水",
            category="survival", status="active",
        )
        no_skills = calc.calculate(goal, {"survivor_skills": []})
        with_skills = calc.calculate(goal, {"survivor_skills": ["水", "净化"]})
        assert with_skills > no_skills

    def test_dependency_penalty(self, calc, db):
        goal = Goal(id="g1", title="Test", category="survival", status="active")
        met = calc.calculate(goal, {"dependency_met": True})
        unmet = calc.calculate(goal, {"dependency_met": False})
        assert met > unmet

    def test_multiplayer_impact_boost(self, calc, db):
        goal = Goal(id="g1", title="Test", category="survival", status="active")
        solo = calc.calculate(goal, {"is_multiplayer": False})
        group = calc.calculate(goal, {"is_multiplayer": True})
        assert group >= solo

    def test_side_task_lower_than_main(self, calc, db):
        main = Task(id="t1", phase=0, priority=0, title="Main", status="pending", task_type="main")
        side = Task(id="t2", phase=0, priority=0, title="Side", status="pending", task_type="side")
        assert calc.calculate(main) > calc.calculate(side)

    def test_score_range_0_to_1(self, calc, db):
        goal = Goal(id="g1", title="Test", category="survival", status="active")
        for urgency in [0.0, 0.5, 1.0]:
            for impact in [0.0, 0.5, 1.0]:
                score = calc.calculate(goal, {"urgency": urgency, "impact": impact})
                assert 0.0 <= score <= 1.0


# ─── Score to Priority Mapping ───────────────────────────────────────────────


class TestScoreToPriority:
    def test_critical_threshold(self, calc):
        assert calc.score_to_priority(0.8) == "critical"
        assert calc.score_to_priority(0.95) == "critical"

    def test_high_threshold(self, calc):
        assert calc.score_to_priority(0.6) == "high"
        assert calc.score_to_priority(0.79) == "high"

    def test_medium_threshold(self, calc):
        assert calc.score_to_priority(0.4) == "medium"
        assert calc.score_to_priority(0.59) == "medium"

    def test_low_threshold(self, calc):
        assert calc.score_to_priority(0.39) == "low"
        assert calc.score_to_priority(0.0) == "low"


# ─── Explain ─────────────────────────────────────────────────────────────────


class TestExplain:
    def test_returns_string(self, calc, db):
        goal = Goal(id="g1", title="找水", category="survival", status="active")
        explanation = calc.explain(goal)
        assert isinstance(explanation, str)
        assert len(explanation) > 0


# ─── GoalEngine Integration ────────────────────────────────────────────────


class TestGoalEngineRecalculate:
    def test_recalculate_priorities(self, db):
        from allspark.services.goal_engine import GoalEngine
        from allspark.services.priority_calculator import PriorityCalculator

        calc = PriorityCalculator(db)
        ge = GoalEngine(db)

        # Create a goal
        goal = ge.add_manual_goal("Test water", category="survival")

        # Recalculate — should update based on context
        ge.recalculate_priorities(calc)

        updated = db.get_goal(goal.id)
        assert updated is not None

    def test_review_goals(self, db):
        from allspark.services.goal_engine import GoalEngine
        from allspark.services.priority_calculator import PriorityCalculator

        calc = PriorityCalculator(db)
        ge = GoalEngine(db)

        # Review with no goals — should not raise
        result = ge.review_goals(calc)
        assert isinstance(result, dict)
