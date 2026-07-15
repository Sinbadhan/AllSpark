"""SHA-151: power_monitor line-coverage tests (criterion 1: total line >=75%).

Exercises simulated readings (with/without DB), source management, manual input,
estimate_runtime / _estimate_hours / _recommend_mode branches, status/history,
and the GPIO fallback path. No hardware in CI.
"""
import threading
from unittest.mock import MagicMock

from allspark.core.database import Database
from allspark.core.models import Resource, ResourceType
from allspark.services import power_monitor as pm_mod
from allspark.services.power_monitor import PowerMonitor


def _power(current=100.0, consumption=50.0, intake=0.0, hours=48.0) -> Resource:
    return Resource(type=ResourceType.POWER, current_amount=current, unit="Wh",
                    daily_consumption=consumption, daily_intake=intake,
                    estimated_remaining_hours=hours, last_updated="",
                    amount_known=True, consumption_known=True, intake_known=True,
                    rate_basis="group_total")


def test_read_simulated_with_db():
    db = MagicMock()
    db.get_resource.return_value = _power(current=200.0, intake=10.0, consumption=50.0)
    m = PowerMonitor(db=db)
    r = m._read_simulated()
    assert r.source == "from_db"
    assert r.energy_wh == 200.0
    assert r.charging is None  # Daily rates are not an instantaneous observation.


def test_read_simulated_no_db():
    m = PowerMonitor()
    r = m._read_simulated()
    assert r.source == "no_data"


def test_read_simulated_db_power_zero():
    db = MagicMock()
    db.get_resource.return_value = _power(current=0.0)
    m = PowerMonitor(db=db)
    reading = m._read_simulated()
    assert reading.source == "from_db"
    assert reading.energy_wh == 0.0
    assert reading.battery_percent is None


def test_read_gpio_fallback_to_simulated(monkeypatch):
    m = PowerMonitor()
    m._gpio_available = True  # force the GPIO path; spidev import fails -> fallback
    r = m._read_gpio()
    assert r.source == "gpio_fallback"


def test_take_reading_uses_simulated_when_no_gpio():
    m = PowerMonitor()
    assert m._take_reading().source == "no_data"


def test_get_current_reading_takes_one_if_empty():
    m = PowerMonitor()
    r = m.get_current_reading()
    assert r.source == "no_data"


def test_register_update_get_sources():
    m = PowerMonitor()
    m.register_source("solar", "solar", available=True)
    assert m.update_source("solar", voltage=12.0, current=2.0, power=24.0) is True
    assert m.update_source("nope") is False
    assert len(m.get_sources()) == 1
    assert len(m.get_active_sources()) == 1
    m.register_source("grid", "grid", available=False)
    assert len(m.get_active_sources()) == 1


def test_get_history_and_status():
    m = PowerMonitor()
    m._history.append(m._take_reading())
    assert len(m.get_history()) == 1
    s = m.get_status()
    assert s["history_entries"] == 1
    assert s["monitoring"] is False


def test_manual_input_with_db(tmp_path):
    db = Database(tmp_path / "pm.db")
    db.upsert_resource(_power())
    m = PowerMonitor(db=db)
    r = m.manual_input(500.0, charging=True, daily_consumption=100.0, daily_intake=20.0)
    assert r["status"] == "ok"
    db.close()


def test_manual_input_no_db():
    m = PowerMonitor()
    r = m.manual_input(100.0)
    assert r["status"] == "ok"


def test_estimate_hours_branches():
    m = PowerMonitor()
    # POWER sustained (consumption <= intake)
    assert m._estimate_hours(_power(consumption=10, intake=20)) == m.SUSTAINED
    # WATER
    w = Resource(type=ResourceType.WATER, current_amount=100, unit="L",
                 daily_consumption=10, daily_intake=0, estimated_remaining_hours=0, last_updated="",
                 amount_known=True, consumption_known=True, intake_known=True,
                 rate_basis="group_total")
    assert m._estimate_hours(w) == 240.0
    # FIRE consumption 0 -> sustained
    f = Resource(type=ResourceType.FIRE, current_amount=5, unit="uses",
                 daily_consumption=0, daily_intake=0, estimated_remaining_hours=0, last_updated="",
                 amount_known=True, consumption_known=True, intake_known=True,
                 rate_basis="group_total")
    assert m._estimate_hours(f) == m.SUSTAINED
    # STORAGE uses remaining GB / net daily growth.
    s = Resource(type=ResourceType.STORAGE, current_amount=10, unit="GB",
                 daily_consumption=100, daily_intake=0, estimated_remaining_hours=0, last_updated="",
                 amount_known=True, consumption_known=True, intake_known=True,
                 rate_basis="group_total")
    assert m._estimate_hours(s) == (10 / 100) * 24


def test_estimate_runtime_with_and_without_db(tmp_path):
    db = Database(tmp_path / "pm2.db")
    db.upsert_resource(_power(hours=80.0))
    m = PowerMonitor(db=db)
    r = m.estimate_runtime()
    assert r["mode_recommendation"] == "proactive"  # 80 >= 72
    db.close()
    m2 = PowerMonitor()
    r2 = m2.estimate_runtime()
    assert r2["mode_recommendation"] == "unknown"


def test_recommend_mode_all_branches():
    m = PowerMonitor()
    assert m._recommend_mode(80) == "proactive"
    assert m._recommend_mode(30) == "standard"
    assert m._recommend_mode(10) == "economy"
    assert m._recommend_mode(3) == "hibernation"


def test_start_stop_monitoring(monkeypatch):
    m = PowerMonitor()
    monkeypatch.setattr(threading, "Thread", MagicMock())
    assert m.start_monitoring()["status"] == "started"
    assert m.start_monitoring()["status"] == "already_running"
    assert m.stop_monitoring()["status"] == "stopped"


def test_monitor_loop_one_iteration_then_stops(monkeypatch):
    m = PowerMonitor()
    monkeypatch.setattr(pm_mod.time, "sleep", lambda s: setattr(m, "_running", False))
    m._running = True
    m._monitor_loop(1)
    assert len(m._history) >= 1


def test_monitor_loop_critical_callback(tmp_path, monkeypatch):
    db = Database(tmp_path / "pm3.db")
    db.upsert_resource(_power(current=5.0, hours=3.0))
    m = PowerMonitor(db=db)
    monkeypatch.setattr(pm_mod.time, "sleep", lambda s: setattr(m, "_running", False))
    m._running = True
    m._monitor_loop(1)  # Runtime is short, but SoC is unknown and cannot trigger.
    db.close()
    # An unknown SoC never triggers the callback.
    m2 = PowerMonitor()
    fired = []
    m2._on_critical = lambda r: fired.append(r)
    monkeypatch.setattr(pm_mod.time, "sleep", lambda s: setattr(m2, "_running", False))
    m2._running = True
    m2._monitor_loop(1)


def test_update_db_handles_exception():
    db = MagicMock()
    db.get_resource.side_effect = RuntimeError("db down")
    m = PowerMonitor(db=db)
    from allspark.services.power_monitor import PowerReading
    m._update_db(PowerReading(timestamp="t", energy_wh=100.0))  # must not raise


def test_monitor_loop_swallows_reading_exception(monkeypatch):
    m = PowerMonitor()
    monkeypatch.setattr(m, "_take_reading", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(pm_mod.time, "sleep", lambda s: setattr(m, "_running", False))
    m._running = True
    m._monitor_loop(1)  # must not raise
