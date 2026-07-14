"""SHA-151: weather line-coverage tests (criterion 1: total line >=75%)."""
from unittest.mock import MagicMock

import pytest

from allspark.core.database import Database
from allspark.services.weather import WeatherPredictor


@pytest.fixture
def wp(tmp_path):
    db = Database(tmp_path / "w.db")
    yield WeatherPredictor(db=db)
    db.close()


def test_get_current_conditions_no_data():
    w = WeatherPredictor()
    c = w.get_current_conditions()
    assert c["pressure_hpa"] is None
    assert c["source"] == "unknown"


def test_get_current_conditions_from_sensor():
    hub = MagicMock()
    hub.get_all_devices.return_value = [
        {"name": "p", "type": "pressure"},
        {"name": "t", "type": "temperature"},
        {"name": "h", "type": "humidity"},
        {"name": "l", "type": "light"},
        {"name": "empty", "type": "pressure"},
    ]
    hub.get_device_readings.side_effect = lambda name, last_n=1: (
        [{"value": 1013.0}] if name == "p" else
        [{"value": 20.0}] if name == "t" else
        [{"value": 60.0}] if name == "h" else
        [{"value": 500.0}] if name == "l" else []
    )
    w = WeatherPredictor(sensor_hub=hub)
    c = w.get_current_conditions()
    assert c["pressure_hpa"] == 1013.0
    assert c["temperature_c"] == 20.0
    assert c["source"] == "sensor"


def test_get_current_conditions_sensor_exception_swallowed():
    hub = MagicMock()
    hub.get_all_devices.side_effect = RuntimeError("hub down")
    w = WeatherPredictor(sensor_hub=hub)
    c = w.get_current_conditions()
    assert c["source"] == "unknown"


def test_get_current_conditions_from_db_manual(wp):
    wp.set_manual_pressure(1010.0)
    c = wp.get_current_conditions()
    assert c["pressure_hpa"] == 1010.0
    assert c["source"] == "manual"


def test_predict_weather_no_pressure():
    w = WeatherPredictor()
    p = w.predict_weather({"pressure_hpa": None})
    assert p["forecast"] == "no_data"


def test_predict_weather_all_pressure_branches():
    w = WeatherPredictor()
    # > 1020 rising/falling
    assert w.predict_weather({"pressure_hpa": 1025, "pressure_trend": "rising"})["forecast"] == "clear"
    assert w.predict_weather({"pressure_hpa": 1025, "pressure_trend": "stable"})["forecast"] == "fair"
    # > 1000 rising/stable/falling
    assert w.predict_weather({"pressure_hpa": 1010, "pressure_trend": "rising"})["forecast"] == "improving"
    assert w.predict_weather({"pressure_hpa": 1010, "pressure_trend": "stable"})["forecast"] == "stable"
    assert w.predict_weather({"pressure_hpa": 1010, "pressure_trend": "falling"})["forecast"] == "deteriorating"
    # > 985 falling/other
    assert w.predict_weather({"pressure_hpa": 990, "pressure_trend": "falling"})["forecast"] == "rain_likely"
    assert w.predict_weather({"pressure_hpa": 990, "pressure_trend": "stable"})["forecast"] == "unsettled"
    # <= 985 storm
    assert w.predict_weather({"pressure_hpa": 980, "pressure_trend": "falling"})["forecast"] == "storm_likely"


def test_predict_weather_humidity_and_cold_addons():
    w = WeatherPredictor()
    p = w.predict_weather({"pressure_hpa": 990, "pressure_trend": "falling", "humidity_pct": 90})
    assert "moderate" in p["severity"] or p["severity"] == "moderate"
    p2 = w.predict_weather({"pressure_hpa": 1010, "pressure_trend": "stable", "temperature_c": 2})
    assert isinstance(p2["advice"], str)


def test_set_manual_pressure_without_db():
    w = WeatherPredictor()
    w.set_manual_pressure(1010.0)  # no db -> no-op, no raise


def test_calculate_trend_branches(wp):
    assert wp._calculate_trend() == "stable"  # no manual pressure history
    # set_manual_pressure uses a per-second timestamp key; insert distinct keys
    # directly so two readings are persisted (same-second calls would collide).
    wp.db.save_hardware_profile("manual_pressure_20260101100000", "1000.0")
    wp.db.save_hardware_profile("manual_pressure_20260101100001", "1010.0")
    assert wp._calculate_trend() == "rising"  # cur 1010 > prev 1000
    wp.db.save_hardware_profile("manual_pressure_20260101100002", "1000.0")
    assert wp._calculate_trend() == "falling"  # cur 1000 < prev 1010


def test_get_manual_pressure_invalid_returns_none(tmp_path):
    db = Database(tmp_path / "w2.db")
    db.save_hardware_profile("manual_pressure", "not-a-number")
    w = WeatherPredictor(db=db)
    assert w._get_manual_pressure() is None
    db.close()


def test_get_cloud_guide():
    assert isinstance(WeatherPredictor().get_cloud_guide(), str)


def test_format_prediction_with_and_without_pressure():
    w = WeatherPredictor()
    out1 = w.format_prediction({"pressure_hpa": 1010, "pressure_trend": "stable", "temperature_c": 20, "humidity_pct": 50})
    assert isinstance(out1, str) and out1
    out2 = w.format_prediction({"pressure_hpa": None})
    assert isinstance(out2, str)


def test_predict_weather_uses_get_current_when_none(wp):
    wp.set_manual_pressure(1010.0)
    p = wp.predict_weather()  # conditions=None -> get_current_conditions
    assert p["forecast"] in ("stable", "improving", "deteriorating")
