import pytest

from allspark.core.database import Database
from allspark.core.models import Resource, ResourceType
from allspark.services.environment import EnvironmentAssessor
from allspark.services.gps_manager import GPSManager


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


class TestGPSManager:
    def test_set_manual_position(self, db):
        gps = GPSManager(db=db)
        pos = gps.set_manual_position(39.9042, 116.4074, 50)
        assert pos["lat"] == 39.9042
        assert pos["lon"] == 116.4074
        assert pos["source"] == "manual"

    def test_get_position_after_set(self, db):
        gps = GPSManager(db=db)
        gps.set_manual_position(31.2304, 121.4737)
        pos = gps.get_position()
        assert pos is not None
        assert abs(pos["lat"] - 31.2304) < 0.001

    def test_get_position_persisted(self, db):
        gps1 = GPSManager(db=db)
        gps1.set_manual_position(35.0, 139.0)
        gps2 = GPSManager(db=db)
        pos = gps2.get_position()
        assert pos is not None
        assert abs(pos["lat"] - 35.0) < 0.001

    def test_calculate_distance(self, db):
        gps = GPSManager(db=db)
        dist = gps.calculate_distance(39.9042, 116.4074, 31.2304, 121.4737)
        assert 1000 < dist < 1200

    def test_calculate_bearing(self, db):
        gps = GPSManager(db=db)
        bearing = gps.calculate_bearing(39.9042, 116.4074, 31.2304, 121.4737)
        assert 0 <= bearing <= 360

    def test_bearing_to_direction(self, db):
        gps = GPSManager(db=db)
        assert gps.bearing_to_direction(0) == "N"
        assert gps.bearing_to_direction(90) == "E"
        assert gps.bearing_to_direction(180) == "S"
        assert gps.bearing_to_direction(270) == "W"

    def test_record_track_point(self, db):
        gps = GPSManager(db=db)
        gps.set_manual_position(40.0, 120.0)
        point_id = gps.record_track_point("camp")
        assert point_id is not None

    def test_format_position(self, db):
        gps = GPSManager(db=db)
        gps.set_manual_position(39.9, 116.4)
        output = gps.format_position()
        assert "39.9" in output
        assert "116.4" in output

    def test_format_position_none(self, db):
        gps = GPSManager(db=db)
        output = gps.format_position(None)
        assert "未知" in output or "unknown" in output.lower()


class TestEnvironmentAssessor:
    def test_assess(self, db):
        env = EnvironmentAssessor(db=db)
        result = env.assess()
        assert "climate" in result
        assert "terrain" in result
        assert "threats" in result
        assert "opportunities" in result
        assert result["status"] == "unknown"
        assert result["overall_score"] is None

    def test_assess_with_low_resources(self, db):
        r = Resource(
            type=ResourceType.POWER, current_amount=10.0, unit="Wh",
            daily_consumption=50.0, daily_intake=0.0,
            estimated_remaining_hours=5.0, last_updated="",
        )
        db.upsert_resource(r)
        env = EnvironmentAssessor(db=db)
        result = env.assess()
        assert result["threats"]["level"] == "high"
        assert any("电力" in f or "Power" in f for f in result["threats"]["factors"])

    def test_assess_with_water_shortage(self, db):
        r = Resource(
            type=ResourceType.WATER, current_amount=1.0, unit="L",
            daily_consumption=3.0, daily_intake=0.0,
            estimated_remaining_hours=8.0, last_updated="",
        )
        db.upsert_resource(r)
        env = EnvironmentAssessor(db=db)
        result = env.assess()
        assert any("水源" in f or "Water" in f for f in result["threats"]["factors"])

    def test_format_assessment(self, db):
        env = EnvironmentAssessor(db=db)
        output = env.format_assessment()
        assert "环境" in output or "Environment" in output
        assert "证据不足" in output or "insufficient" in output.lower()

    def test_recommendations(self, db):
        env = EnvironmentAssessor(db=db)
        result = env.assess()
        assert len(result["recommendations"]) > 0
