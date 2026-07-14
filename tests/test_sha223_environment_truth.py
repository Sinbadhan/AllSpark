from datetime import datetime, timedelta
from pathlib import Path

import pytest

from allspark.core.database import Database
from allspark.core.models import MapPOI, ResourceType
from allspark.services.environment import EnvironmentAssessor
from allspark.services.resource_manager import ResourceManager
from allspark.services.survival_engine import SurvivalAssessmentEngine
from allspark.services.weather import WeatherPredictor
from tests.test_web_ui_v11 import TempDb, _client


class StubWeather:
    def __init__(self, observed_at: str, *, stale: bool = False):
        self.observed_at = observed_at
        self.stale = stale

    def get_current_conditions(self) -> dict:
        return {
            "pressure_hpa": 1013.0,
            "pressure_trend": "stable",
            "temperature_c": 20.0,
            "humidity_pct": 50.0,
            "source": "sensor",
            "observed_at": self.observed_at,
            "stale": self.stale,
        }

    def predict_weather(self, conditions=None) -> dict:
        return {
            "forecast": "stable",
            "confidence": 0.7,
            "severity": "normal",
            "advice": "",
        }


@pytest.fixture
def environment_parts(tmp_path: Path):
    db = Database(tmp_path / "environment.db")
    resource_manager = ResourceManager(db)
    resource_manager.init_defaults()
    survival = SurvivalAssessmentEngine(db, resource_manager)
    yield db, resource_manager, survival
    db.close()


def _fresh_weather() -> StubWeather:
    return StubWeather(datetime.now().isoformat())


def _seed_terrain(db: Database) -> None:
    db.save_poi(
        MapPOI(
            id="shelter-1",
            name="Shelter",
            type="shelter",
            discovered_at=datetime.now().isoformat(),
            verified=True,
        )
    )


def _configure_core_resources(resource_manager: ResourceManager) -> None:
    resource_manager.update_resource(
        ResourceType.POWER, 100.0, consumption=50.0, intake=0.0
    )
    resource_manager.update_resource(
        ResourceType.WATER, 20.0, consumption=2.0, intake=0.0
    )
    resource_manager.update_resource(
        ResourceType.FOOD, 30000.0, consumption=2000.0, intake=0.0
    )


def _assessor(db, resource_manager, survival, weather) -> EnvironmentAssessor:
    return EnvironmentAssessor(
        db=db,
        weather=weather,
        resource_mgr=resource_manager,
        survival=survival,
    )


def test_fresh_install_is_unknown_not_neutral(environment_parts) -> None:
    db, resource_manager, survival = environment_parts
    result = _assessor(
        db, resource_manager, survival, WeatherPredictor(db=db)
    ).assess()

    assert result["status"] == "unknown"
    assert result["overall_score"] is None
    assert set(result["completeness"]["missing"]) == {
        "climate",
        "terrain",
        "resources",
    }
    assert result["opportunities"]["items"] == []
    assert result["threats"] == {
        "level": "unknown",
        "score": None,
        "factors": [],
    }
    assert result["resource_evidence"]["power"]["status"] == "unknown"
    assert result["sources"]["resources"] == {
        "source": "unknown",
        "observed_at": None,
        "stale": False,
    }
    assert all("explor" not in rec.lower() for rec in result["recommendations"])
    formatted = _assessor(
        db, resource_manager, survival, WeatherPredictor(db=db)
    ).format_assessment(result)
    assert "climate" in formatted or "气候" in formatted
    assert "time unknown" in formatted or "时间未知" in formatted


def test_partial_resources_distinguish_zero_sustained_and_unknown(
    environment_parts,
) -> None:
    db, resource_manager, survival = environment_parts
    _seed_terrain(db)
    resource_manager.update_resource(
        ResourceType.POWER, 0.0, consumption=10.0, intake=0.0
    )
    resource_manager.update_resource(
        ResourceType.WATER, 10.0, consumption=0.0, intake=0.0
    )

    result = _assessor(
        db, resource_manager, survival, _fresh_weather()
    ).assess()

    assert result["status"] == "unknown"
    assert result["overall_score"] is None
    assert result["resource_evidence"]["power"]["status"] == "zero"
    assert result["resource_evidence"]["water"]["status"] == "sustained"
    assert result["resource_evidence"]["food"]["status"] == "unknown"
    assert result["sources"]["resources"]["source"] == "database_partial"
    assert result["threats"]["level"] == "high"
    assert any(
        "power" in factor.lower() or "电力" in factor
        for factor in result["threats"]["factors"]
    )
    assert "resources" in result["completeness"]["missing"]


def test_no_weather_data_blocks_actionable_score(environment_parts) -> None:
    db, resource_manager, survival = environment_parts
    _configure_core_resources(resource_manager)
    _seed_terrain(db)

    result = _assessor(
        db, resource_manager, survival, WeatherPredictor(db=db)
    ).assess()

    assert result["climate"]["condition"] == "no_data"
    assert result["climate"]["score"] is None
    assert result["sources"]["climate"]["source"] == "unknown"
    assert result["overall_score"] is None
    assert "climate" in result["completeness"]["missing"]


def test_stale_sensor_blocks_actionable_score(environment_parts) -> None:
    db, resource_manager, survival = environment_parts
    _configure_core_resources(resource_manager)
    _seed_terrain(db)
    observed_at = (datetime.now() - timedelta(hours=7)).isoformat()

    result = _assessor(
        db,
        resource_manager,
        survival,
        StubWeather(observed_at, stale=True),
    ).assess()

    assert result["status"] == "unknown"
    assert result["sources"]["climate"]["observed_at"] == observed_at
    assert result["sources"]["climate"]["stale"] is True
    assert result["overall_score"] is None


def test_complete_evidence_allows_scoring_and_opportunities(
    environment_parts,
) -> None:
    db, resource_manager, survival = environment_parts
    _configure_core_resources(resource_manager)
    _seed_terrain(db)

    result = _assessor(
        db, resource_manager, survival, _fresh_weather()
    ).assess()

    assert result["status"] == "assessed"
    assert result["completeness"]["complete"] is True
    assert result["completeness"]["ratio"] == 1.0
    assert result["completeness"]["missing"] == []
    assert isinstance(result["overall_score"], float)
    assert 0.0 <= result["overall_score"] <= 1.0
    assert result["sources"]["climate"]["source"] == "sensor"
    assert result["sources"]["resources"]["observed_at"]
    assert result["opportunities"]["items"]


def test_fresh_install_environment_api_is_explicitly_unknown() -> None:
    with TempDb() as path:
        client = _client(path)
        body = client.get("/api/environment").json()

    assert body["status"] == "unknown"
    assert body["overall_score"] is None
    assert set(body["completeness"]["missing"]) == {
        "climate",
        "terrain",
        "resources",
    }
    assert body["opportunities"]["items"] == []
