import json
import time
import threading
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Callable

from allspark.models import ResourceType

logger = logging.getLogger(__name__)


@dataclass
class PowerReading:
    timestamp: str
    voltage_v: float = 0.0
    current_a: float = 0.0
    power_w: float = 0.0
    energy_wh: float = 0.0
    source: str = "unknown"
    battery_percent: float = 0.0
    charging: bool = False


@dataclass
class PowerSource:
    name: str
    type: str
    available: bool = False
    voltage_v: float = 0.0
    current_a: float = 0.0
    power_w: float = 0.0


class PowerMonitor:
    def __init__(self, db=None):
        self.db = db
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._current_reading = PowerReading(timestamp="")
        self._sources: dict[str, PowerSource] = {}
        self._history: list[PowerReading] = []
        self._on_critical: Optional[Callable] = None
        self._gpio_available = False
        self._check_gpio()

    def _check_gpio(self):
        try:
            import RPi.GPIO
            self._gpio_available = True
        except ImportError:
            self._gpio_available = False

    def start_monitoring(self, interval_seconds: int = 60,
                         on_critical: Optional[Callable] = None) -> dict:
        if self._running:
            return {"status": "already_running"}

        self._on_critical = on_critical
        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(interval_seconds,),
            daemon=True,
        )
        self._monitor_thread.start()
        return {"status": "started", "interval_s": interval_seconds, "gpio": self._gpio_available}

    def stop_monitoring(self) -> dict:
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        return {"status": "stopped"}

    def _monitor_loop(self, interval: int):
        while self._running:
            try:
                reading = self._take_reading()
                self._current_reading = reading
                self._history.append(reading)
                if len(self._history) > 1440:
                    self._history = self._history[-1440:]

                if self.db:
                    self._update_db(reading)

                if reading.battery_percent < 10 and reading.power_w > 0:
                    if self._on_critical:
                        try:
                            self._on_critical(reading)
                        except Exception:
                            pass

            except Exception as e:
                logger.warning(f"Power monitoring error: {e}")

            time.sleep(interval)

    def _take_reading(self) -> PowerReading:
        if self._gpio_available:
            return self._read_gpio()
        return self._read_simulated()

    def _read_gpio(self) -> PowerReading:
        reading = PowerReading(timestamp=datetime.now().isoformat())
        try:
            import spidev
            spi = spidev.SpiDev(0, 0)
            spi.max_speed_hz = 1000000

            raw = spi.xfer2([0x06, 0x00])
            adc_value = ((raw[0] & 0x0F) << 8) | raw[1]
            voltage = adc_value * 3.3 / 4095.0

            battery_voltage = voltage * 5.0
            reading.voltage_v = round(battery_voltage, 2)
            reading.battery_percent = max(0, min(100, (battery_voltage / 12.6) * 100))
            reading.charging = battery_voltage > 12.8
            reading.source = "gpio_adc"

            spi.close()
        except Exception as e:
            logger.debug(f"GPIO read failed: {e}")
            reading = self._read_simulated()
            reading.source = "gpio_fallback"

        return reading

    def _read_simulated(self) -> PowerReading:
        if self.db:
            power = self.db.get_resource(ResourceType.POWER)
            if power:
                hours = power.estimated_remaining_hours
                pct = min(100, max(0, (hours / 72.0) * 100))
                return PowerReading(
                    timestamp=datetime.now().isoformat(),
                    voltage_v=round(3.7 + (pct / 100) * 0.5, 2),
                    current_a=round(power.daily_consumption / 24.0 / 3.7, 3) if power.daily_consumption > 0 else 0,
                    power_w=round(power.daily_consumption / 24.0, 2) if power.daily_consumption > 0 else 0,
                    energy_wh=power.current_amount,
                    battery_percent=round(pct, 1),
                    charging=power.daily_intake > power.daily_consumption,
                    source="simulated",
                )

        return PowerReading(
            timestamp=datetime.now().isoformat(),
            voltage_v=3.7,
            current_a=0.5,
            power_w=1.85,
            energy_wh=37.0,
            battery_percent=50.0,
            charging=False,
            source="default",
        )

    def _update_db(self, reading: PowerReading):
        try:
            power = self.db.get_resource(ResourceType.POWER)
            if power and reading.energy_wh > 0:
                power.current_amount = reading.energy_wh
                if reading.charging and reading.power_w > 0:
                    power.daily_intake = reading.power_w * 24
                self.db.upsert_resource(power)
        except Exception as e:
            logger.warning(f"DB update error: {e}")

    def get_current_reading(self) -> PowerReading:
        if not self._current_reading.timestamp:
            return self._take_reading()
        return self._current_reading

    def register_source(self, name: str, source_type: str,
                        available: bool = False) -> PowerSource:
        source = PowerSource(
            name=name,
            type=source_type,
            available=available,
        )
        self._sources[name] = source
        return source

    def update_source(self, name: str, available: bool = None,
                      voltage: float = None, current: float = None,
                      power: float = None) -> bool:
        source = self._sources.get(name)
        if not source:
            return False
        if available is not None:
            source.available = available
        if voltage is not None:
            source.voltage_v = voltage
        if current is not None:
            source.current_a = current
        if power is not None:
            source.power_w = power
        return True

    def get_sources(self) -> list[PowerSource]:
        return list(self._sources.values())

    def get_active_sources(self) -> list[PowerSource]:
        return [s for s in self._sources.values() if s.available]

    def get_history(self, last_n: int = 100) -> list[dict]:
        readings = self._history[-last_n:]
        return [
            {
                "timestamp": r.timestamp,
                "voltage_v": r.voltage_v,
                "current_a": r.current_a,
                "power_w": r.power_w,
                "energy_wh": r.energy_wh,
                "battery_percent": r.battery_percent,
                "charging": r.charging,
                "source": r.source,
            }
            for r in readings
        ]

    def get_status(self) -> dict:
        reading = self.get_current_reading()
        return {
            "monitoring": self._running,
            "gpio_available": self._gpio_available,
            "current": {
                "voltage_v": reading.voltage_v,
                "current_a": reading.current_a,
                "power_w": reading.power_w,
                "energy_wh": reading.energy_wh,
                "battery_percent": reading.battery_percent,
                "charging": reading.charging,
                "source": reading.source,
            },
            "sources_registered": len(self._sources),
            "sources_active": len(self.get_active_sources()),
            "history_entries": len(self._history),
        }

    def manual_input(self, energy_wh: float, charging: bool = False,
                     daily_consumption: float = None,
                     daily_intake: float = None) -> dict:
        reading = PowerReading(
            timestamp=datetime.now().isoformat(),
            energy_wh=energy_wh,
            battery_percent=min(100, max(0, (energy_wh / 37.0) * 100)),
            charging=charging,
            source="manual",
        )
        self._current_reading = reading

        if self.db:
            power = self.db.get_resource(ResourceType.POWER)
            if power:
                power.current_amount = energy_wh
                if daily_consumption is not None:
                    power.daily_consumption = daily_consumption
                if daily_intake is not None:
                    power.daily_intake = daily_intake
                power.estimated_remaining_hours = self._estimate_hours(power)
                self.db.upsert_resource(power)

        return {"status": "ok", "reading": {
            "energy_wh": reading.energy_wh,
            "battery_percent": reading.battery_percent,
            "charging": reading.charging,
        }}

    def _estimate_hours(self, power) -> float:
        from allspark.models import ResourceType
        if power.type == ResourceType.POWER:
            if power.daily_consumption <= power.daily_intake:
                return 9999.0
            net_hourly = (power.daily_consumption - power.daily_intake) / 24.0
            if net_hourly <= 0:
                return 9999.0
            return power.current_amount / net_hourly
        elif power.type in (ResourceType.WATER, ResourceType.FOOD):
            if power.daily_consumption <= 0:
                return 9999.0
            return (power.current_amount / power.daily_consumption) * 24.0
        elif power.type == ResourceType.FIRE:
            if power.daily_consumption <= 0:
                return 9999.0
            return power.current_amount * 24.0
        return 0.0

    def estimate_runtime(self) -> dict:
        reading = self.get_current_reading()
        if self.db:
            power = self.db.get_resource(ResourceType.POWER)
            if power:
                return {
                    "energy_wh": power.current_amount,
                    "consumption_wh_per_day": power.daily_consumption,
                    "intake_wh_per_day": power.daily_intake,
                    "estimated_hours": power.estimated_remaining_hours,
                    "mode_recommendation": self._recommend_mode(power.estimated_remaining_hours),
                }
        return {"estimated_hours": 0, "mode_recommendation": "hibernation"}

    def _recommend_mode(self, hours: float) -> str:
        if hours >= 72:
            return "proactive"
        elif hours >= 24:
            return "standard"
        elif hours >= 6:
            return "economy"
        return "hibernation"
