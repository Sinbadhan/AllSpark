import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class SensorType(Enum):
    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"
    PRESSURE = "pressure"
    GPS = "gps"
    LIGHT = "light"
    AIR_QUALITY = "air_quality"
    MOTION = "motion"
    WATER_LEVEL = "water_level"


@dataclass
class SensorReading:
    sensor_type: str
    timestamp: str
    value: float
    unit: str
    status: str = "ok"
    source: str = "unknown"


@dataclass
class SensorDevice:
    name: str
    sensor_type: str
    interface: str
    available: bool = False
    last_reading: Optional[SensorReading] = None
    read_interval: int = 60


@dataclass
class EnvironmentSnapshot:
    timestamp: str
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    pressure_hpa: Optional[float] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude_m: Optional[float] = None
    light_lux: Optional[float] = None
    air_quality_ppm: Optional[float] = None
    water_level_cm: Optional[float] = None


class SensorHub:
    def __init__(self, db=None):
        self.db = db
        self._devices: dict[str, SensorDevice] = {}
        self._readings: dict[str, list[SensorReading]] = {}
        self._running = False
        self._poll_thread: Optional[threading.Thread] = None
        self._on_alert: Optional[Callable] = None
        self._i2c_available = False
        self._gpio_available = False
        self._check_interfaces()

    def _check_interfaces(self):
        try:
            import importlib.util
            self._gpio_available = importlib.util.find_spec("RPi.GPIO") is not None
        except (ImportError, ValueError):
            pass
        try:
            import importlib.util
            self._i2c_available = importlib.util.find_spec("smbus2") is not None
        except (ImportError, ValueError):
            pass

    def register_device(self, name: str, sensor_type: str,
                        interface: str = "auto",
                        read_interval: int = 60) -> SensorDevice:
        if interface == "auto":
            if self._i2c_available and sensor_type in (
                SensorType.TEMPERATURE.value, SensorType.HUMIDITY.value,
                SensorType.PRESSURE.value,
            ):
                interface = "i2c"
            elif self._gpio_available:
                interface = "gpio"
            else:
                interface = "simulated"

        device = SensorDevice(
            name=name,
            sensor_type=sensor_type,
            interface=interface,
            available=(interface != "simulated"),
            read_interval=read_interval,
        )
        self._devices[name] = device
        self._readings[name] = []
        return device

    def start_polling(self, on_alert: Optional[Callable] = None) -> dict:
        if self._running:
            return {"status": "already_running"}

        self._on_alert = on_alert
        self._running = True
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True
        )
        self._poll_thread.start()
        return {"status": "started", "devices": len(self._devices)}

    def stop_polling(self) -> dict:
        self._running = False
        if self._poll_thread:
            self._poll_thread.join(timeout=5)
        return {"status": "stopped"}

    def _poll_loop(self):
        while self._running:
            for name, device in self._devices.items():
                try:
                    reading = self._read_device(device)
                    device.last_reading = reading
                    self._readings[name].append(reading)
                    if len(self._readings[name]) > 1440:
                        self._readings[name] = self._readings[name][-1440:]

                    self._check_alerts(device, reading)

                except Exception as e:
                    logger.debug(f"Sensor {name} read error: {e}")

            time.sleep(30)

    def _read_device(self, device: SensorDevice) -> SensorReading:
        if device.interface == "i2c":
            return self._read_i2c(device)
        elif device.interface == "gpio":
            return self._read_gpio(device)
        elif device.interface == "serial":
            return self._read_serial(device)
        return self._read_simulated(device)

    def _read_i2c(self, device: SensorDevice) -> SensorReading:
        reading = SensorReading(
            sensor_type=device.sensor_type,
            timestamp=datetime.now().isoformat(),
            value=0.0,
            unit="",
            source="i2c",
        )

        try:
            import smbus2
            bus = smbus2.SMBus(1)

            if device.sensor_type == SensorType.TEMPERATURE.value:
                data = bus.read_i2c_block_data(0x44, 0x00, 6)
                raw_temp = (data[0] << 8) | data[1]
                reading.value = round(-45 + (175 * raw_temp / 65535.0), 1)
                reading.unit = "°C"
            elif device.sensor_type == SensorType.HUMIDITY.value:
                data = bus.read_i2c_block_data(0x44, 0x00, 6)
                raw_hum = (data[3] << 8) | data[4]
                reading.value = round(100 * raw_hum / 65535.0, 1)
                reading.unit = "%"
            elif device.sensor_type == SensorType.PRESSURE.value:
                data = bus.read_i2c_block_data(0x60, 0x00, 4)
                raw_press = (data[1] << 16) | (data[2] << 8) | data[3]
                reading.value = round(raw_press / 65536.0, 1)
                reading.unit = "hPa"

            bus.close()
        except Exception as e:
            logger.debug(f"I2C read failed: {e}")
            reading = self._read_simulated(device)
            reading.source = "i2c_fallback"

        return reading

    def _read_gpio(self, device: SensorDevice) -> SensorReading:
        reading = SensorReading(
            sensor_type=device.sensor_type,
            timestamp=datetime.now().isoformat(),
            value=0.0,
            unit="",
            source="gpio",
        )

        try:
            import RPi.GPIO as GPIO
            if device.sensor_type == SensorType.MOTION.value:
                GPIO.setmode(GPIO.BCM)
                pin = 17
                GPIO.setup(pin, GPIO.IN)
                reading.value = float(GPIO.input(pin))
                reading.unit = "binary"
            elif device.sensor_type == SensorType.WATER_LEVEL.value:
                GPIO.setmode(GPIO.BCM)
                pin = 18
                GPIO.setup(pin, GPIO.IN)
                reading.value = float(GPIO.input(pin))
                reading.unit = "binary"
        except Exception as e:
            logger.debug(f"GPIO read failed: {e}")
            reading = self._read_simulated(device)
            reading.source = "gpio_fallback"

        return reading

    def _read_serial(self, device: SensorDevice) -> SensorReading:
        reading = SensorReading(
            sensor_type=device.sensor_type,
            timestamp=datetime.now().isoformat(),
            value=0.0,
            unit="",
            source="serial",
        )

        try:
            import serial
            if device.sensor_type == SensorType.GPS.value:
                ser = serial.Serial("/dev/serial0", 9600, timeout=1)
                for _ in range(10):
                    line = ser.readline().decode("ascii", errors="ignore").strip()
                    if line.startswith("$GPGGA") or line.startswith("$GNGGA"):
                        parts = line.split(",")
                        if len(parts) > 5 and parts[2] and parts[4]:
                            lat = float(parts[2]) / 100.0
                            lon = float(parts[4]) / 100.0
                            reading.value = lat
                            reading.unit = f"lat={lat},lon={lon}"
                        break
                ser.close()
        except Exception as e:
            logger.debug(f"Serial read failed: {e}")
            reading = self._read_simulated(device)
            reading.source = "serial_fallback"

        return reading

    def _read_simulated(self, device: SensorDevice) -> SensorReading:
        units = {
            SensorType.TEMPERATURE.value: "°C",
            SensorType.HUMIDITY.value: "%",
            SensorType.PRESSURE.value: "hPa",
            SensorType.GPS.value: "lat",
            SensorType.LIGHT.value: "lux",
            SensorType.AIR_QUALITY.value: "ppm",
            SensorType.MOTION.value: "binary",
            SensorType.WATER_LEVEL.value: "cm",
        }

        return SensorReading(
            sensor_type=device.sensor_type,
            timestamp=datetime.now().isoformat(),
            value=None,
            unit=units.get(device.sensor_type, ""),
            status="no_data",
            source="no_data",
        )

    def _check_alerts(self, device: SensorDevice, reading: SensorReading):
        if not self._on_alert:
            return

        from allspark.core.i18n import t
        alerts = []
        if device.sensor_type == SensorType.TEMPERATURE.value:
            if reading.value < 0 or reading.value > 45:
                alerts.append(f"{t('sensor_temp_alert')}: {reading.value}{reading.unit}")
        elif device.sensor_type == SensorType.AIR_QUALITY.value:
            if reading.value > 200:
                alerts.append(f"{t('sensor_air_alert')}: {reading.value}{reading.unit}")
        elif device.sensor_type == SensorType.WATER_LEVEL.value:
            if reading.value > 50:
                alerts.append(f"{t('sensor_water_alert')}: {reading.value}{reading.unit}")

        for alert in alerts:
            try:
                self._on_alert(device.name, alert)
            except Exception:
                pass

    def manual_input(self, device_name: str, value: float) -> Optional[SensorReading]:
        device = self._devices.get(device_name)
        if not device:
            return None

        units = {
            SensorType.TEMPERATURE.value: "°C",
            SensorType.HUMIDITY.value: "%",
            SensorType.PRESSURE.value: "hPa",
            SensorType.LIGHT.value: "lux",
            SensorType.AIR_QUALITY.value: "ppm",
            SensorType.WATER_LEVEL.value: "cm",
        }

        reading = SensorReading(
            sensor_type=device.sensor_type,
            timestamp=datetime.now().isoformat(),
            value=value,
            unit=units.get(device.sensor_type, ""),
            status="manual",
            source="manual",
        )
        device.last_reading = reading
        self._readings[device_name].append(reading)
        return reading

    def get_snapshot(self) -> EnvironmentSnapshot:
        snap = EnvironmentSnapshot(timestamp=datetime.now().isoformat())

        for name, device in self._devices.items():
            if not device.last_reading:
                continue
            r = device.last_reading
            if device.sensor_type == SensorType.TEMPERATURE.value:
                snap.temperature_c = r.value
            elif device.sensor_type == SensorType.HUMIDITY.value:
                snap.humidity_pct = r.value
            elif device.sensor_type == SensorType.PRESSURE.value:
                snap.pressure_hpa = r.value
            elif device.sensor_type == SensorType.GPS.value:
                if "lat=" in r.unit:
                    parts = r.unit.replace("lat=", "").split(",lon=")
                    if len(parts) == 2:
                        snap.latitude = float(parts[0])
                        snap.longitude = float(parts[1])
            elif device.sensor_type == SensorType.LIGHT.value:
                snap.light_lux = r.value
            elif device.sensor_type == SensorType.AIR_QUALITY.value:
                snap.air_quality_ppm = r.value
            elif device.sensor_type == SensorType.WATER_LEVEL.value:
                snap.water_level_cm = r.value

        return snap

    def get_device_readings(self, device_name: str, last_n: int = 100) -> list[dict]:
        readings = self._readings.get(device_name, [])[-last_n:]
        return [
            {
                "timestamp": r.timestamp,
                "value": r.value,
                "unit": r.unit,
                "status": r.status,
                "source": r.source,
            }
            for r in readings
        ]

    def get_all_devices(self) -> list[dict]:
        result = []
        for name, device in self._devices.items():
            result.append({
                "name": name,
                "type": device.sensor_type,
                "interface": device.interface,
                "available": device.available,
                "last_value": device.last_reading.value if device.last_reading else None,
                "last_unit": device.last_reading.unit if device.last_reading else None,
                "last_source": device.last_reading.source if device.last_reading else None,
                "readings_count": len(self._readings.get(name, [])),
            })
        return result

    def get_status(self) -> dict:
        return {
            "polling": self._running,
            "i2c_available": self._i2c_available,
            "gpio_available": self._gpio_available,
            "devices_registered": len(self._devices),
            "devices_active": sum(1 for d in self._devices.values() if d.available),
            "total_readings": sum(len(v) for v in self._readings.values()),
        }

    def auto_detect(self) -> list[dict]:
        detected = []
        if self._i2c_available:
            try:
                import smbus2
                bus = smbus2.SMBus(1)
                common_addresses = {
                    0x44: ("SHT30", SensorType.TEMPERATURE.value),
                    0x76: ("BME280", SensorType.PRESSURE.value),
                    0x77: ("BMP180", SensorType.PRESSURE.value),
                }
                for addr, (name, stype) in common_addresses.items():
                    try:
                        bus.read_byte(addr)
                        detected.append({"address": hex(addr), "name": name, "type": stype, "interface": "i2c"})
                    except Exception:
                        pass
                bus.close()
            except Exception:
                pass

        return detected
