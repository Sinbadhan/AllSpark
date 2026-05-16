import pytest

from allspark.database import Database
from allspark.reset_manager import ResetManager
from allspark.models import ResetLevel, Goal, Resource, ResourceType
from allspark.i18n import set_language


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture
def rm(db):
    return ResetManager(db=db)


class TestResetEvaluation:
    def test_l1_evaluation(self, rm):
        result = rm.evaluate_reset(ResetLevel.ASSESSMENT)
        assert result["level"] == 1
        assert result["allowed"] is True
        assert len(result["affected_data"]) > 0

    def test_l2_evaluation(self, rm):
        result = rm.evaluate_reset(ResetLevel.ARCHIVE)
        assert result["level"] == 2
        assert result["allowed"] is True
        assert len(result["affected_data"]) > len(
            rm.evaluate_reset(ResetLevel.ASSESSMENT)["affected_data"]
        )

    def test_l3_evaluation(self, rm):
        result = rm.evaluate_reset(ResetLevel.FACTORY)
        assert result["level"] == 3
        assert result["allowed"] is True
        assert any("irreversible" in w.lower() or "不可逆" in w for w in result["warnings"])


class TestResetExecution:
    def test_l1_reset(self, rm, db):
        goal = Goal(
            id="g1", title="Test Goal", goal_type="manual",
            category="survival", priority="medium", status="active",
            source="survivor", created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )
        db.save_goal(goal)

        result = rm.execute_reset(ResetLevel.ASSESSMENT)
        assert result["status"] == "ok"
        assert result["level"] == "ASSESSMENT"

        goals_after = db.get_active_goals()
        assert len(goals_after) == 1

    def test_l2_reset(self, rm, db):
        goal = Goal(
            id="g2", title="Test Goal 2", goal_type="manual",
            category="survival", priority="medium", status="active",
            source="survivor", created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )
        db.save_goal(goal)
        r = Resource(
            type=ResourceType.POWER, current_amount=100.0, unit="Wh",
            daily_consumption=50.0, daily_intake=0.0,
            estimated_remaining_hours=48.0, last_updated="",
        )
        db.upsert_resource(r)

        result = rm.execute_reset(ResetLevel.ARCHIVE)
        assert result["status"] == "ok"

        goals_after = db.get_active_goals()
        assert len(goals_after) == 0

    def test_l3_reset(self, rm, db):
        r = Resource(
            type=ResourceType.POWER, current_amount=100.0, unit="Wh",
            daily_consumption=50.0, daily_intake=0.0,
            estimated_remaining_hours=48.0, last_updated="",
        )
        db.upsert_resource(r)

        result = rm.execute_reset(ResetLevel.FACTORY, force=True)
        assert result["status"] == "ok"

        power = db.get_resource(ResourceType.POWER)
        assert power is None


class TestResetCooldown:
    def test_cooldown_after_reset(self, rm):
        rm.execute_reset(ResetLevel.ASSESSMENT)
        status = rm.get_reset_status()
        assert status["can_reset"] is False

    def test_no_cooldown_initially(self, rm):
        status = rm.get_reset_status()
        assert status["can_reset"] is True

    def test_rejected_during_cooldown(self, rm):
        rm.execute_reset(ResetLevel.ASSESSMENT)
        result = rm.evaluate_reset(ResetLevel.ASSESSMENT)
        assert result["allowed"] is False


class TestResetStatus:
    def test_initial_status(self, rm):
        status = rm.get_reset_status()
        assert status["last_reset"] is None
        assert status["can_reset"] is True

    def test_status_after_reset(self, rm):
        rm.execute_reset(ResetLevel.ASSESSMENT)
        status = rm.get_reset_status()
        assert status["last_reset"] is not None
