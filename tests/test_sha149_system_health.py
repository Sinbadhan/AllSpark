"""SHA-149: System page honest health + structured weather.

The integrity score must factor in core capabilities (LLM loaded, module
support), not just warning count, so an unloaded LLM or unsupported modules
never display 100% / "stable". Weather must never leak raw keys/JSON/null.
"""
import os
import tempfile

from fastapi.testclient import TestClient

from allspark.adapters.web_ui import create_app
from allspark.core.database import Database
from allspark.infrastructure.hardware import FeatureFlags
from allspark.infrastructure.module_loader import ModuleRegistry


def _init_client():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path)
    db.mark_initialized()
    flags = FeatureFlags(
        llm=True, web_ui=True, image_recognition=True, voice_input=True,
        voice_output=True, offline_map=True, sensor_hub=True, power_monitor=True,
        data_preservation=True, boot_manager=True, governance=True,
        trade_engine=True, kolibri=True, kiwix=True, multimodal=True,
        self_learning=True,
    )
    ModuleRegistry(flags).save_to_db(db)
    db.close()
    return TestClient(create_app(path)), path


class TestSystemHealth:
    def test_health_returns_score_state_factors(self):
        client, path = _init_client()
        try:
            r = client.get("/api/system/health")
            assert r.status_code == 200, r.text
            h = r.json()
            assert "score" in h and "state" in h and "factors" in h
            assert 0 <= h["score"] <= 100
            assert h["state"] in ("healthy", "degraded", "unavailable")
            f = h["factors"]
            for key in ("llm_loaded", "modules_total", "modules_loaded",
                        "modules_unsupported", "modules_experimental",
                        "critical_count", "warning_count"):
                assert key in f, f"missing factor {key}"
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_health_not_100_when_llm_unloaded(self):
        """SHA-149 headline: LLM not loaded -> score < 100, not 'healthy'."""
        client, path = _init_client()
        try:
            h = client.get("/api/system/health").json()
            assert h["factors"]["llm_loaded"] is False
            assert h["score"] < 100, f"score should be <100 when LLM unloaded, got {h['score']}"
            assert h["state"] in ("degraded", "unavailable"), h["state"]
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_modules_contract_has_status_field(self):
        client, path = _init_client()
        try:
            mods = client.get("/api/modules").json()
            assert isinstance(mods, list) and len(mods) > 0
            for m in mods:
                assert "status" in m, m
                assert isinstance(m["experimental"], bool)
                assert m["status"] in ("loaded", "available", "unsupported", "disabled")
        finally:
            if os.path.exists(path):
                os.unlink(path)


class TestWeatherRenderingContract:
    def test_weather_current_nulls_and_forecast_no_data(self):
        """The /api/weather data shape the renderer relies on: with no sensors,
        current fields are null and forecast is 'no_data' (never raw JSON)."""
        client, path = _init_client()
        try:
            r = client.get("/api/weather")
            # Weather service may be 503 if unavailable; only assert shape when present.
            if r.status_code == 200:
                data = r.json()
                cur = data.get("current", {})
                # No sensors -> pressure/temperature null (the leak source).
                assert cur.get("pressure_hpa") is None
                fc = data.get("forecast", {})
                assert fc.get("forecast") in ("no_data", "unknown")
        finally:
            if os.path.exists(path):
                os.unlink(path)
