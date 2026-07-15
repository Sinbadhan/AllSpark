import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from allspark.core.models import ResourceType

logger = logging.getLogger(__name__)


@dataclass
class PowerReading:
    timestamp: str
    voltage_v: Optional[float] = None
    current_a: Optional[float] = None
    power_w: Optional[float] = None
    energy_wh: Optional[float] = None
    source: str = "unknown"
    battery_percent: Optional[float] = None
    battery_percent_source: Optional[str] = None
    battery_percent_as_of: Optional[str] = None
    battery_percent_trusted: bool = False
    charging: Optional[bool] = None

    @property
    def has_trusted_battery_percent(self) -> bool:
        """Whether SoC came directly from a trusted, timestamped device."""
        return bool(
            self.battery_percent_trusted
            and self.battery_percent_source
            and self.battery_percent_as_of
            and self.battery_percent is not None
            and 0 <= self.battery_percent <= 100
        )


@dataclass
class PowerSource:
    name: str
    type: str
    available: bool = False
    voltage_v: Optional[float] = None
    current_a: Optional[float] = None
    power_w: Optional[float] = None


class PowerMonitor:
    def __init__(self, db=None, resource_manager=None):
        self.db = db
        self.resource_manager = resource_manager
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
            import importlib.util
            self._gpio_available = importlib.util.find_spec("RPi.GPIO") is not None
        except (ImportError, ValueError):
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

                if (
                    reading.has_trusted_battery_percent
                    and reading.battery_percent is not None
                    and reading.battery_percent < 10
                ):
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
            manager = self._get_resource_manager()
            if (
                power
                and power.amount_known
                and manager.has_complete_rate_data(power)
            ):
                return PowerReading(
                    timestamp=datetime.now().isoformat(),
                    energy_wh=power.current_amount,
                    source="from_db",
                )
            if power and power.amount_known:
                return PowerReading(
                    timestamp=datetime.now().isoformat(),
                    energy_wh=power.current_amount,
                    source="from_db_partial",
                )

        return PowerReading(
            timestamp=datetime.now().isoformat(),
            source="no_data",
        )

    def _update_db(self, reading: PowerReading):
        try:
            power = self.db.get_resource(ResourceType.POWER)
            if power and reading.energy_wh is not None:
                manager = self._get_resource_manager()
                manager.merge_resource_observation(
                    ResourceType.POWER,
                    amount=reading.energy_wh,
                    intake=(
                        reading.power_w * 24
                        if reading.charging is True
                        and reading.power_w is not None
                        and reading.power_w > 0
                        else None
                    ),
                    source="sensor",
                    as_of=reading.timestamp,
                )
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
        return [self._reading_payload(r, include_timestamp=True) for r in readings]

    @staticmethod
    def _reading_payload(reading: PowerReading, *, include_timestamp: bool = False) -> dict:
        soc_known = reading.has_trusted_battery_percent
        payload = {
            "voltage_v": reading.voltage_v,
            "current_a": reading.current_a,
            "power_w": reading.power_w,
            "energy_wh": reading.energy_wh,
            "battery_percent": reading.battery_percent if soc_known else None,
            "battery_percent_known": soc_known,
            "battery_percent_source": reading.battery_percent_source if soc_known else None,
            "battery_percent_as_of": reading.battery_percent_as_of if soc_known else None,
            "charging": reading.charging,
            "source": reading.source,
        }
        if include_timestamp:
            payload = {"timestamp": reading.timestamp, **payload}
        return payload

    def get_status(self) -> dict:
        reading = self.get_current_reading()
        return {
            "monitoring": self._running,
            "gpio_available": self._gpio_available,
            "current": self._reading_payload(reading),
            "sources_registered": len(self._sources),
            "sources_active": len(self.get_active_sources()),
            "history_entries": len(self._history),
        }

    def manual_input(self, energy_wh: float, charging: Optional[bool] = None,
                     daily_consumption: float = None,
                     daily_intake: float = None) -> dict:
        manager = self._get_resource_manager()
        energy_wh = manager.validate_value("amount", energy_wh)
        if self.db:
            power = self.db.get_resource(ResourceType.POWER)
            if power:
                manager.merge_resource_observation(
                    ResourceType.POWER,
                    amount=energy_wh,
                    consumption=daily_consumption,
                    intake=daily_intake,
                    source="user_input",
                    as_of=datetime.now().isoformat(),
                )

        reading = PowerReading(
            timestamp=datetime.now().isoformat(),
            energy_wh=energy_wh,
            charging=charging,
            source="manual",
        )
        self._current_reading = reading

        return {"status": "ok", "reading": self._reading_payload(reading)}

    # Sentinel: -1 means "sustained / cannot estimate".
    SUSTAINED = -1.0

    def _get_resource_manager(self):
        if self.resource_manager is not None:
            return self.resource_manager
        from allspark.services.resource_manager import ResourceManager

        return ResourceManager(self.db)

    def _estimate_hours(self, power) -> float:
        return self._get_resource_manager().estimate_remaining(power)

    def estimate_runtime(self) -> dict:
        self.get_current_reading()
        if self.db:
            power = self.db.get_resource(ResourceType.POWER)
            manager = self._get_resource_manager()
            if power and manager.remaining_status(power) != "unknown":
                mode = (
                    "proactive"
                    if power.estimated_remaining_hours == self.SUSTAINED
                    else self._recommend_mode(power.estimated_remaining_hours)
                )
                return {
                    "energy_wh": power.current_amount,
                    "consumption_wh_per_day": power.daily_consumption,
                    "intake_wh_per_day": power.daily_intake,
                    "estimated_hours": power.estimated_remaining_hours,
                    "mode_recommendation": mode,
                }
        return {"estimated_hours": None, "mode_recommendation": "unknown"}

    def _recommend_mode(self, hours: float) -> str:
        if hours >= 72:
            return "proactive"
        elif hours >= 24:
            return "standard"
        elif hours >= 6:
            return "economy"
        return "hibernation"
