"""SHA-151: sensor_hub line-coverage tests (criterion 1: total line >=75%).

Exercises the simulated mode (no hardware), manual input, snapshot, alerts,
status, polling control, and the i2c/gpio/serial fallback paths. All hardware
libs are absent in CI so every read falls back to simulated.
"""
import threading
from unittest.mock import MagicMock

from allspark.services.sensor_hub import SensorHub, SensorType


def test_register_device_auto_falls_back_to_simulated():
    hub = SensorHub()
    d = hub.register_device("t1", SensorType.TEMPERATURE.value)
    assert d.interface == "simulated"
    assert d.available is False


def test_register_device_explicit_interfaces():
    hub = SensorHub()
    for iface in ("i2c", "gpio", "serial", "simulated"):
        d = hub.register_device(f"d-{iface}", SensorType.TEMPERATURE.value, interface=iface)
        assert d.interface == iface


def test_read_simulated_all_sensor_types():
    hub = SensorHub()
    for st in SensorType:
        d = hub.register_device(st.value, st.value, interface="simulated")
        r = hub._read_simulated(d)
        assert r.status == "no_data"
        assert r.sensor_type == st.value


def test_read_device_routes_by_interface():
    hub = SensorHub()
    # i2c device without hardware -> _read_i2c falls back to simulated.
    d_i2c = hub.register_device("i2c1", SensorType.TEMPERATURE.value, interface="i2c")
    r = hub._read_device(d_i2c)
    assert r.source in ("i2c_fallback", "no_data")
    # gpio device without hardware -> fallback.
    d_gpio = hub.register_device("gpio1", SensorType.MOTION.value, interface="gpio")
    assert hub._read_device(d_gpio).source in ("gpio_fallback", "no_data")
    # serial device without hardware -> fallback.
    d_serial = hub.register_device("ser1", SensorType.GPS.value, interface="serial")
    assert hub._read_device(d_serial).source in ("serial_fallback", "no_data")
    # simulated -> no_data.
    d_sim = hub.register_device("sim1", SensorType.HUMIDITY.value, interface="simulated")
    assert hub._read_device(d_sim).source == "no_data"


def test_manual_input_not_found_and_ok():
    hub = SensorHub()
    assert hub.manual_input("nope", 1.0) is None
    hub.register_device("t1", SensorType.TEMPERATURE.value)
    r = hub.manual_input("t1", 22.5)
    assert r is not None
    assert r.value == 22.5
    assert r.source == "manual"


def test_get_snapshot_maps_sensor_types():
    hub = SensorHub()
    hub.register_device("t", SensorType.TEMPERATURE.value)
    hub.manual_input("t", 25.0)
    hub.register_device("h", SensorType.HUMIDITY.value)
    hub.manual_input("h", 60.0)
    hub.register_device("w", SensorType.WATER_LEVEL.value)
    hub.manual_input("w", 30.0)
    snap = hub.get_snapshot()
    assert snap.temperature_c == 25.0
    assert snap.humidity_pct == 60.0
    assert snap.water_level_cm == 30.0


def test_get_snapshot_gps_parsing():
    hub = SensorHub()
    hub.register_device("g", SensorType.GPS.value)
    # Simulate a GPS reading with the lat=/lon= unit format.
    from datetime import datetime

    from allspark.services.sensor_hub import SensorReading
    dev = hub._devices["g"]
    dev.last_reading = SensorReading("gps", datetime.now().isoformat(), 1.0, "lat=40.5,lon=-74.0", "ok", "manual")
    snap = hub.get_snapshot()
    assert snap.latitude == 40.5
    assert snap.longitude == -74.0


def test_get_snapshot_skips_devices_without_reading():
    hub = SensorHub()
    hub.register_device("t", SensorType.TEMPERATURE.value)  # no manual_input -> no last_reading
    snap = hub.get_snapshot()
    assert snap.temperature_c is None


def test_get_device_readings_and_all_devices():
    hub = SensorHub()
    hub.register_device("t", SensorType.TEMPERATURE.value)
    hub.manual_input("t", 1.0)
    hub.manual_input("t", 2.0)
    assert len(hub.get_device_readings("t")) == 2
    assert hub.get_device_readings("nope") == []
    devs = hub.get_all_devices()
    assert len(devs) == 1
    assert devs[0]["last_value"] == 2.0


def test_get_status():
    hub = SensorHub()
    hub.register_device("t", SensorType.TEMPERATURE.value)
    s = hub.get_status()
    assert s["devices_registered"] == 1
    assert s["polling"] is False


def test_check_alerts_no_callback():
    hub = SensorHub()
    hub.register_device("t", SensorType.TEMPERATURE.value)
    dev = hub._devices["t"]
    from datetime import datetime

    from allspark.services.sensor_hub import SensorReading
    r = SensorReading("temperature", datetime.now().isoformat(), 50.0, "°C")
    hub._check_alerts(dev, r)  # no callback -> no-op, no raise


def test_check_alerts_temperature_and_callback_exception():
    hub = SensorHub()
    hub.register_device("t", SensorType.TEMPERATURE.value)
    dev = hub._devices["t"]
    from datetime import datetime

    from allspark.services.sensor_hub import SensorReading
    calls = []
    hub._on_alert = lambda name, alert: calls.append((name, alert))
    hub._check_alerts(dev, SensorReading("temperature", datetime.now().isoformat(), 50.0, "°C"))
    assert calls  # temp > 45 -> alert
    # Callback that raises is swallowed.
    hub._on_alert = MagicMock(side_effect=RuntimeError("boom"))
    hub._check_alerts(dev, SensorReading("temperature", datetime.now().isoformat(), -5.0, "°C"))  # temp < 0


def test_check_alerts_air_quality_and_water_level():
    hub = SensorHub()
    from datetime import datetime

    from allspark.services.sensor_hub import SensorReading
    calls = []
    hub._on_alert = lambda name, alert: calls.append(alert)
    hub.register_device("a", SensorType.AIR_QUALITY.value)
    hub._check_alerts(hub._devices["a"], SensorReading("air_quality", datetime.now().isoformat(), 250.0, "ppm"))
    hub.register_device("w", SensorType.WATER_LEVEL.value)
    hub._check_alerts(hub._devices["w"], SensorReading("water_level", datetime.now().isoformat(), 60.0, "cm"))
    assert len(calls) == 2


def test_start_stop_polling(monkeypatch):
    hub = SensorHub()
    hub.register_device("t", SensorType.TEMPERATURE.value)
    monkeypatch.setattr("allspark.services.sensor_hub.time.sleep", lambda s: None)
    monkeypatch.setattr(threading, "Thread", MagicMock())
    assert hub.start_polling()["status"] == "started"
    assert hub.start_polling()["status"] == "already_running"
    assert hub.stop_polling()["status"] == "stopped"


def test_poll_loop_runs_one_iteration(monkeypatch):
    hub = SensorHub()
    hub.register_device("t", SensorType.TEMPERATURE.value)
    monkeypatch.setattr("allspark.services.sensor_hub.time.sleep", lambda s: setattr(hub, "_running", False))
    hub._running = True
    hub._poll_loop()
    assert hub._devices["t"].last_reading is not None


def test_auto_detect_no_i2c_returns_empty():
    hub = SensorHub()  # no smbus2 in CI -> _i2c_available False
    assert hub.auto_detect() == []
