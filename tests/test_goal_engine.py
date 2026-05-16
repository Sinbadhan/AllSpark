import pytest

from allspark.database import Database
from allspark.goal_engine import GoalEngine
from allspark.models import Goal, Milestone, ResourceType, Resource
from allspark.i18n import set_language


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture
def ge(db):
    return GoalEngine(db=db)


class TestGoalEngineManual:
    def test_add_manual_goal(self, ge):
        goal = ge.add_manual_goal("Build radio tower")
        assert goal.title == "Build radio tower"
        assert goal.goal_type == "manual"
        assert goal.source == "survivor"
        assert goal.status == "active"

    def test_add_manual_goal_with_milestones(self, ge):
        goal = ge.add_manual_goal(
            "Find water",
            description="Locate water source",
            category="survival",
            priority="high",
            created_by="Alice",
            milestone_descriptions=["Survey area", "Test water", "Store water"],
        )
        assert goal.milestone_count == 3
        assert goal.milestone_done == 0

        milestones = ge.db.get_milestones_by_goal(goal.id)
        assert len(milestones) == 3
        assert all(not ms.done for ms in milestones)

    def test_complete_goal(self, ge, db):
        goal = ge.add_manual_goal("Test goal", milestone_descriptions=["Step 1", "Step 2"])
        ge.complete_milestone(f"{goal.id}-m1")
        ge.complete_milestone(f"{goal.id}-m2")

        updated = db.get_goal(goal.id)
        assert updated.progress == 1.0
        assert updated.status == "completed"

    def test_abandon_goal(self, ge, db):
        goal = ge.add_manual_goal("Test goal", priority="medium")
        result = ge.abandon_goal(goal.id)
        assert result is True
        updated = db.get_goal(goal.id)
        assert updated.status == "abandoned"

    def test_cannot_abandon_critical(self, ge, db):
        goal = ge.add_manual_goal("Critical goal", priority="critical")
        result = ge.abandon_goal(goal.id)
        assert result is False
        updated = db.get_goal(goal.id)
        assert updated.status == "active"

    def test_pause_and_resume(self, ge, db):
        goal = ge.add_manual_goal("Test goal", priority="medium")
        assert ge.pause_goal(goal.id) is True
        assert db.get_goal(goal.id).status == "paused"

        assert ge.resume_goal(goal.id) is True
        assert db.get_goal(goal.id).status == "active"

    def test_cannot_pause_critical(self, ge):
        goal = ge.add_manual_goal("Critical", priority="critical")
        assert ge.pause_goal(goal.id) is False


class TestGoalEngineAutoGenerate:
    def test_auto_generate_with_low_water(self, ge, db):
        water = Resource(
            type=ResourceType.WATER, current_amount=2.0, unit="L",
            daily_consumption=3.0, daily_intake=0.0,
            estimated_remaining_hours=16.0, last_updated="",
        )
        db.upsert_resource(water)

        generated = ge.auto_generate_goals()
        water_goals = [g for g in generated if g.id.startswith("water-")]
        assert len(water_goals) >= 1
        assert water_goals[0].priority == "critical"
        assert water_goals[0].goal_type == "auto"
        assert water_goals[0].milestone_count > 0

    def test_auto_generate_no_duplicate(self, ge, db):
        water = Resource(
            type=ResourceType.WATER, current_amount=2.0, unit="L",
            daily_consumption=3.0, daily_intake=0.0,
            estimated_remaining_hours=16.0, last_updated="",
        )
        db.upsert_resource(water)

        first = ge.auto_generate_goals()
        second = ge.auto_generate_goals()
        assert len(second) == 0


class TestGoalEngineSummary:
    def test_summary_no_goals(self, ge):
        set_language("zh", persist=False)
        summary = ge.get_goal_summary()
        assert "暂无" in summary or "No" in summary

    def test_summary_with_goals(self, ge, db):
        ge.add_manual_goal("Find water", priority="critical")
        summary = ge.get_goal_summary()
        assert "Find water" in summary

    def test_goal_detail(self, ge, db):
        goal = ge.add_manual_goal(
            "Build shelter",
            milestone_descriptions=["Assess", "Build", "Verify"],
        )
        detail = ge.get_goal_detail(goal.id)
        assert detail is not None
        assert detail["goal"].title == "Build shelter"
        assert len(detail["milestones"]) == 3

    def test_goal_detail_not_found(self, ge):
        assert ge.get_goal_detail("nonexistent") is None


class TestGoalEngineProgress:
    def test_partial_progress(self, ge, db):
        goal = ge.add_manual_goal(
            "Test goal",
            milestone_descriptions=["Step 1", "Step 2", "Step 3"],
        )
        ge.complete_milestone(f"{goal.id}-m1")
        updated = db.get_goal(goal.id)
        assert abs(updated.progress - 1/3) < 0.01
        assert updated.milestone_done == 1
        assert updated.status == "active"

    def test_check_goal_progress(self, ge, db):
        notifications = ge.check_goal_progress()
        assert isinstance(notifications, list)
