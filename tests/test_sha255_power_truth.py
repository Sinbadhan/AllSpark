"""SHA-255: power telemetry must not manufacture measurements or battery SoC."""

import sys
from io import StringIO
from types import SimpleNamespace

import pytest
from rich.console import Console

from allspark.commands.hardware import PowerCommand
from allspark.core.database import Database
from allspark.core.i18n import get_language, set_language
from allspark.core.models import ResourceType
from allspark.services import power_monitor as pm_mod
from allspark.services.power_monitor import PowerMonitor, PowerReading
from allspark.services.resource_manager import ResourceManager


def test_gpio_adc_reports_voltage_without_manufacturing_soc_or_live_state(monkeypatch):
    class FakeSpi:
        def __init__(self, bus, device):
            assert (bus, device) == (0, 0)
            self.max_speed_hz = 0

        def xfer2(self, payload):
            assert payload == [0x06, 0x00]
            return [0x06, 0x00]

        def close(self):
            return None

    monkeypatch.setitem(sys.modules, "spidev", SimpleNamespace(SpiDev=FakeSpi))
    reading = PowerMonitor()._read_gpio()

    assert reading.source == "gpio_adc"
    assert reading.voltage_v is not None
    assert reading.voltage_v > 0
    assert reading.current_a is None
    assert reading.power_w is None
    assert reading.energy_wh is None
    assert reading.charging is None
    assert reading.battery_percent is None
    assert reading.has_trusted_battery_percent is False


@pytest.mark.parametrize(
    ("consumption", "intake", "intake_known", "expected_hours"),
    [
        (50.0, 0.0, True, 48.0),
        (50.0, 50.0, True, PowerMonitor.SUSTAINED),
        (50.0, None, False, None),
    ],
)
def test_manual_wh_never_derives_soc_or_charging_from_runtime(
    tmp_path, consumption, intake, intake_known, expected_hours
):
    db = Database(tmp_path / "power-truth.db")
    manager = ResourceManager(db)
    manager.init_defaults()
    manager.update_resource(
        ResourceType.POWER,
        100,
        consumption=consumption,
        intake=intake,
        intake_known=intake_known,
    )
    monitor = PowerMonitor(db=db, resource_manager=manager)

    result = monitor.manual_input(100)
    reading = result["reading"]
    assert reading["energy_wh"] == 100
    assert reading["battery_percent"] is None
    assert reading["battery_percent_known"] is False
    assert reading["charging"] is None
    assert monitor.estimate_runtime()["estimated_hours"] == expected_hours
    db.close()


def test_status_and_history_fail_closed_without_trusted_soc_metadata():
    monitor = PowerMonitor()
    untrusted = PowerReading(
        timestamp="2026-07-15T12:00:00+08:00",
        voltage_v=12.1,
        battery_percent=5,
        source="gpio_adc",
    )
    monitor._current_reading = untrusted
    monitor._history.append(untrusted)

    status = monitor.get_status()["current"]
    history = monitor.get_history()[0]
    for payload in (status, history):
        assert payload["voltage_v"] == 12.1
        assert payload["battery_percent"] is None
        assert payload["battery_percent_known"] is False
        assert payload["battery_percent_source"] is None
        assert payload["battery_percent_as_of"] is None


def test_trusted_timestamped_device_soc_is_structured_and_can_alert(monkeypatch):
    reading = PowerReading(
        timestamp="2026-07-15T12:00:00+08:00",
        battery_percent=5,
        battery_percent_source="trusted_bms",
        battery_percent_as_of="2026-07-15T12:00:00+08:00",
        battery_percent_trusted=True,
        source="battery_management_system",
    )
    monitor = PowerMonitor()
    fired = []
    monitor._on_critical = fired.append
    monkeypatch.setattr(monitor, "_take_reading", lambda: reading)
    monkeypatch.setattr(pm_mod.time, "sleep", lambda _: setattr(monitor, "_running", False))
    monitor._running = True
    monitor._monitor_loop(1)

    assert fired == [reading]
    payload = monitor.get_status()["current"]
    assert payload["battery_percent"] == 5
    assert payload["battery_percent_known"] is True
    assert payload["battery_percent_source"] == "trusted_bms"
    assert payload["battery_percent_as_of"] == "2026-07-15T12:00:00+08:00"


def test_unknown_soc_never_triggers_critical_callback(monkeypatch):
    reading = PowerReading(
        timestamp="2026-07-15T12:00:00+08:00",
        power_w=100,
        battery_percent=1,
        source="gpio_adc",
    )
    monitor = PowerMonitor()
    fired = []
    monitor._on_critical = fired.append
    monkeypatch.setattr(monitor, "_take_reading", lambda: reading)
    monkeypatch.setattr(pm_mod.time, "sleep", lambda _: setattr(monitor, "_running", False))
    monitor._running = True
    monitor._monitor_loop(1)

    assert fired == []


@pytest.mark.parametrize("invalid_soc", [float("nan"), -1.0, 101.0, float("inf")])
def test_invalid_trusted_soc_is_unknown_in_payload_cli_and_callback(
    invalid_soc, monkeypatch
):
    reading = PowerReading(
        timestamp="2026-07-15T12:00:00+08:00",
        power_w=100,
        battery_percent=invalid_soc,
        battery_percent_source="trusted_bms",
        battery_percent_as_of="2026-07-15T12:00:00+08:00",
        battery_percent_trusted=True,
        source="battery_management_system",
    )
    assert reading.has_trusted_battery_percent is False

    monitor = PowerMonitor()
    monitor._current_reading = reading
    monitor._history.append(reading)
    assert monitor.get_status()["current"]["battery_percent"] is None
    assert monitor.get_history()[0]["battery_percent"] is None

    container = SimpleNamespace(db=None, get=lambda name: monitor)
    command = PowerCommand(container)
    output = StringIO()
    command.console = Console(file=output, force_terminal=False, color_system=None)
    set_language("en", persist=False)
    try:
        command.execute([])
    finally:
        set_language("zh", persist=False)
    rendered = output.getvalue()
    assert "Unknown for now" in rendered
    assert f"{invalid_soc}%" not in rendered

    fired = []
    monitor._on_critical = fired.append
    monkeypatch.setattr(monitor, "_take_reading", lambda: reading)
    monkeypatch.setattr(pm_mod.time, "sleep", lambda _: setattr(monitor, "_running", False))
    monitor._running = True
    monitor._monitor_loop(1)
    assert fired == []


@pytest.mark.parametrize(
    ("lang", "unknown_text"),
    [("zh", "暂时未知"), ("en", "Unknown for now")],
)
def test_power_cli_localizes_unknown_measurements_without_none_percent(
    lang, unknown_text
):
    monitor = PowerMonitor()
    container = SimpleNamespace(db=None, get=lambda name: monitor)
    command = PowerCommand(container)
    output = StringIO()
    command.console = Console(file=output, force_terminal=False, color_system=None)
    set_language(lang, persist=False)
    try:
        command.execute([])
    finally:
        set_language("zh", persist=False)

    rendered = output.getvalue()
    assert unknown_text in rendered
    assert "None%" not in rendered
    assert "0.0V" not in rendered
    assert "0.0A" not in rendered
    assert "0.0W" not in rendered


def test_power_history_cli_does_not_format_unknown_as_none_percent():
    monitor = PowerMonitor()
    monitor._history.append(PowerReading(timestamp="2026-07-15T12:00:00+08:00"))
    container = SimpleNamespace(db=None, get=lambda name: monitor)
    command = PowerCommand(container)
    output = StringIO()
    command.console = Console(file=output, force_terminal=False, color_system=None)
    previous_language = get_language()
    set_language("zh", persist=False)
    try:
        command.execute(["history"])
    finally:
        set_language(previous_language, persist=False)

    rendered = output.getvalue()
    assert "暂时未知" in rendered
    assert "None%" not in rendered
    assert "NoneWh" not in rendered


def test_power_source_cli_lists_every_registered_source():
    monitor = PowerMonitor()
    monitor.register_source("solar", "solar", available=True)
    monitor.register_source("grid", "grid", available=False)
    container = SimpleNamespace(db=None, get=lambda name: monitor)
    command = PowerCommand(container)
    output = StringIO()
    command.console = Console(file=output, force_terminal=False, color_system=None)
    previous_language = get_language()
    set_language("zh", persist=False)
    try:
        command.execute(["source"])
    finally:
        set_language(previous_language, persist=False)

    rendered = output.getvalue()
    assert "solar (solar)" in rendered
    assert "grid (grid)" in rendered
    assert rendered.count("暂时未知") == 2


@pytest.mark.parametrize(
    ("lang", "value", "message"),
    [
        ("zh", "大概在充", "无法识别充电状态"),
        ("en", "maybe", "Unrecognized charging state"),
    ],
)
def test_power_input_rejects_ambiguous_charging_without_writing(lang, value, message):
    monitor = PowerMonitor()
    container = SimpleNamespace(db=None, get=lambda name: monitor)
    command = PowerCommand(container)
    output = StringIO()
    command.console = Console(file=output, force_terminal=False, color_system=None)
    set_language(lang, persist=False)
    try:
        command.execute(["input", "100", value])
    finally:
        set_language("zh", persist=False)

    assert message in output.getvalue()
    assert monitor._current_reading.timestamp == ""


@pytest.mark.parametrize(
    ("lang", "args", "message"),
    [
        ("zh", ["input"], "必须提供当前能量 Wh"),
        ("en", ["input"], "Current energy in Wh is required"),
        ("zh", ["input", "not-a-number"], "必须是数值"),
        ("en", ["input", "nan"], "must be a finite number"),
        ("zh", ["input", "inf"], "必须是有限数值"),
        ("en", ["input", "-1"], "cannot be negative"),
    ],
)
def test_power_input_rejects_missing_or_invalid_wh_without_writing(
    lang, args, message
):
    monitor = PowerMonitor()
    container = SimpleNamespace(db=None, get=lambda name: monitor)
    command = PowerCommand(container)
    output = StringIO()
    command.console = Console(file=output, force_terminal=False, color_system=None)
    previous_language = get_language()
    set_language(lang, persist=False)
    try:
        command.execute(args)
    finally:
        set_language(previous_language, persist=False)

    assert message in output.getvalue()
    assert monitor._current_reading.timestamp == ""


@pytest.mark.parametrize(
    ("token", "expected"),
    [("charging", True), ("充电", True), ("not-charging", False), ("未充电", False)],
)
def test_power_input_accepts_only_explicit_charging_tokens(token, expected):
    monitor = PowerMonitor()
    container = SimpleNamespace(db=None, get=lambda name: monitor)
    command = PowerCommand(container)
    command.console = Console(file=StringIO(), force_terminal=False, color_system=None)

    command.execute(["input", "100", token])

    assert monitor.get_current_reading().charging is expected
