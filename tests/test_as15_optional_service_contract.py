"""Synthetic service contracts do not certify any physical hardware."""
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient

from allspark.adapters.web_ui import create_app
from allspark.infrastructure.hardware import HardwareTier, compute_feature_flags
from allspark.infrastructure.module_loader import EXPERIMENTAL_MODULES, ModuleRegistry
from tests.regression._harness import (
    Recorder,
    blocking_records,
    http_probe,
    initialization_payload,
    optional_service_profile,
)
from tests.regression.suite_web_api import _run_disabled_contracts


@contextmanager
def client(tmp_path, *, enabled=False, language="en"):
    with optional_service_profile(enabled=enabled):
        app = create_app(str(tmp_path / "app.db"))
        with TestClient(app, headers={"X-AllSpark-Request": "1"}) as c:
            response = c.post("/api/init/complete", json=initialization_payload(c, language=language))
            assert response.status_code == 200, response.text
            yield c


@pytest.mark.parametrize("tier", list(HardwareTier))
def test_manual_position_is_not_gated_on_sensor_hardware(tier):
    flags = compute_feature_flags(tier, False)
    flags.sensor_hub = False
    registry = ModuleRegistry(flags)
    assert registry.should_load("gps_manager")
    assert not registry.should_load("sensor_hub")
    status = next(row for row in registry.format_status_dict() if row["name"] == "gps_manager")
    assert status["hardware_capable"] and status["dependency_installed"]
    assert status["release_status"] == "experimental"
    assert {"gps_manager", "sensor_hub", "weather", "trade_engine"} <= EXPERIMENTAL_MODULES


def test_disabled_contract_matrix_is_exact_and_bilingual(tmp_path):
    recorder = Recorder(tmp_path / "disabled.jsonl")
    try:
        with client(tmp_path) as c:
            _run_disabled_contracts(c, recorder)
            assert c.get("/api/gps").json() == {"location": None}
            assert c.app.state.container.get("sensor_hub") is None
        assert len(recorder.records) == 16
        assert not blocking_records(recorder.records)
        assert all(row.flags == ["exact_contract_pass"] for row in recorder.records)
    finally:
        recorder.close()


@pytest.mark.parametrize("language", ["zh", "en"])
def test_enabled_software_services_return_real_contracts_not_mock_responses(tmp_path, language):
    with client(tmp_path, enabled=True, language=language) as c:
        assert c.get("/api/trade/list").json() == {"trades": []}
        assert c.post("/api/trade/propose", json={}).status_code == 400
        weather = c.get("/api/weather")
        assert weather.status_code == 200
        assert set(weather.json()) == {"current", "forecast", "guide"}
        assert c.post("/api/weather/pressure", json={"hpa": 1012}).json() == {
            "status": "ok", "pressure_hpa": 1012.0,
        }
        assert c.get("/api/environment").status_code == 200
        hub = c.app.state.container.require("sensor_hub")
        assert hub.get_status()["polling"] is False
        assert hub.get_all_devices() == []
        snapshot = c.get("/api/sensor/snapshot")
        assert snapshot.status_code == 200
        assert all(value is None for key, value in snapshot.json().items() if key != "timestamp")


@pytest.mark.parametrize("language", ["zh", "en"])
def test_manual_position_invalid_bodies_do_not_overwrite_location(tmp_path, language):
    with client(tmp_path, language=language) as c:
        assert c.get("/api/gps").json() == {"location": None}
        response = c.post("/api/gps/set", json={"latitude": 31.23, "longitude": 121.47})
        assert response.status_code == 200, response.text
        location = response.json()["location"]
        assert (location["lat"], location["lon"], location["source"]) == (31.23, 121.47, "manual")
        for body in ({}, [], None, {"lat": 1}, {"lng": 1}, {"lat": True, "lng": 1},
                     {"lat": "bad", "lng": 1}, {"lat": 91, "lng": 1}, {"lat": 1, "lng": 181},
                     {"lat": 1, "lng": 2, "alt": "inf"}, {"lat": "nan", "lng": 2}):
            rejected = c.post("/api/gps/set", json=body)
            assert 400 <= rejected.status_code < 500, (body, rejected.text)
            assert rejected.json()["status"] == "error"
            assert c.get("/api/gps").json() == {"location": location}
        assert c.post("/api/gps/set", json={"lat": 0, "lng": 0, "alt": 0}).status_code == 200
        assert c.get("/api/gps").json()["location"]["lat"] == 0
    # A second application reads the explicitly saved position, without sensors.
    with TestClient(create_app(str(tmp_path / "app.db"))) as restored:
        assert restored.get("/api/gps").json()["location"]["source"] == "manual"


@pytest.mark.parametrize("status,body,passes", [
    (503, {"status": "error", "error": "expected"}, True),
    (500, {"status": "error", "error": "expected"}, False),
    (503, {"status": "error", "error": "wrong service"}, False),
    (200, {"status": "error", "error": "expected"}, False),
])
def test_exact_contract_cannot_allowlist_arbitrary_failures(tmp_path, status, body, passes):
    recorder = Recorder(tmp_path / "probe.jsonl")
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=body))
    try:
        with httpx.Client(transport=transport, base_url="http://test") as c:
            result = http_probe(c, "GET", "/optional", recorder=recorder,
                                expected_response=(503, {"status": "error", "error": "expected"}))
        assert bool(blocking_records([result])) is not passes
        assert "degraded_allowlisted" not in result.flags
    finally:
        recorder.close()
