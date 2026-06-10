from typing import Optional

from allspark.core.i18n import t


class WeatherPredictor:
    def __init__(self, db=None, sensor_hub=None):
        self.db = db
        self.sensor_hub = sensor_hub

    def get_current_conditions(self) -> dict:
        result = {
            "pressure_hpa": None,
            "pressure_trend": "stable",
            "temperature_c": None,
            "humidity_pct": None,
            "light_level": None,
            "source": "unknown",
        }

        if self.sensor_hub:
            try:
                for dev in self.sensor_hub.get_all_devices():
                    readings = self.sensor_hub.get_device_readings(dev["name"], last_n=1)
                    if not readings:
                        continue
                    r = readings[0]
                    dev_type = dev.get("type", "")
                    if dev_type == "pressure":
                        result["pressure_hpa"] = r.get("value")
                    elif dev_type == "temperature":
                        result["temperature_c"] = r.get("value")
                    elif dev_type == "humidity":
                        result["humidity_pct"] = r.get("value")
                    elif dev_type == "light":
                        result["light_level"] = r.get("value")
                if result["pressure_hpa"] is not None:
                    result["source"] = "sensor"
            except Exception:
                pass

        if result["pressure_hpa"] is None and self.db:
            result["source"] = "manual"
            result["pressure_hpa"] = self._get_manual_pressure()

        if result["pressure_hpa"] is not None:
            result["pressure_trend"] = self._calculate_trend()

        return result

    def predict_weather(self, conditions: dict = None) -> dict:
        if conditions is None:
            conditions = self.get_current_conditions()

        prediction = {
            "forecast": "unknown",
            "confidence": 0.0,
            "severity": "normal",
            "advice": "",
            "time_horizon_hours": 12,
        }

        pressure = conditions.get("pressure_hpa")
        trend = conditions.get("pressure_trend", "stable")
        humidity = conditions.get("humidity_pct")
        temp = conditions.get("temperature_c")

        if pressure is None:
            prediction["forecast"] = "no_data"
            prediction["advice"] = t("weather_no_pressure")
            return prediction

        if pressure > 1020:
            if trend == "rising":
                prediction["forecast"] = "clear"
                prediction["confidence"] = 0.7
                prediction["advice"] = t("weather_clear_rising")
            else:
                prediction["forecast"] = "fair"
                prediction["confidence"] = 0.6
                prediction["advice"] = t("weather_fair_stable")

        elif pressure > 1000:
            if trend == "rising":
                prediction["forecast"] = "improving"
                prediction["confidence"] = 0.5
                prediction["advice"] = t("weather_improving")
            elif trend == "stable":
                prediction["forecast"] = "stable"
                prediction["confidence"] = 0.5
                prediction["advice"] = t("weather_stable")
            else:
                prediction["forecast"] = "deteriorating"
                prediction["confidence"] = 0.5
                prediction["advice"] = t("weather_deteriorating")

        elif pressure > 985:
            if trend == "falling":
                prediction["forecast"] = "rain_likely"
                prediction["confidence"] = 0.65
                prediction["severity"] = "moderate"
                prediction["advice"] = t("weather_rain_likely")
            else:
                prediction["forecast"] = "unsettled"
                prediction["confidence"] = 0.5
                prediction["advice"] = t("weather_unsettled")

        else:
            prediction["forecast"] = "storm_likely"
            prediction["confidence"] = 0.75
            prediction["severity"] = "severe"
            prediction["advice"] = t("weather_storm_likely")

        if humidity is not None and humidity > 85 and trend == "falling":
            if prediction["severity"] == "normal":
                prediction["severity"] = "moderate"
            prediction["advice"] += " " + t("weather_humidity_rain")

        if temp is not None and temp < 5:
            prediction["advice"] += " " + t("weather_cold_warning")

        return prediction

    def get_cloud_guide(self) -> str:
        return t("weather_cloud_guide")

    def set_manual_pressure(self, pressure_hpa: float):
        if self.db:
            from datetime import datetime
            ts_key = f"manual_pressure_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            self.db.save_hardware_profile(ts_key, str(pressure_hpa))
            self.db.save_hardware_profile("manual_pressure", str(pressure_hpa))

    def _get_manual_pressure(self) -> Optional[float]:
        if not self.db:
            return None
        try:
            row = self.db.conn.execute(
                "SELECT value FROM hardware_profile WHERE key='manual_pressure'"
            ).fetchone()
            return float(row[0]) if row else None
        except (ValueError, TypeError):
            return None

    def _calculate_trend(self) -> str:
        if not self.db:
            return "stable"
        try:
            rows = self.db.conn.execute(
                "SELECT value FROM hardware_profile WHERE key LIKE 'manual_pressure_%' ORDER BY key DESC LIMIT 2"
            ).fetchall()
            if len(rows) < 2:
                return "stable"
            prev = float(rows[1][0])
            cur = float(rows[0][0])
            diff = cur - prev
            if diff > 2.0:
                return "rising"
            elif diff < -2.0:
                return "falling"
            return "stable"
        except (ValueError, TypeError, IndexError):
            return "stable"

    def format_prediction(self, conditions: dict = None) -> str:
        conditions = conditions or self.get_current_conditions()
        prediction = self.predict_weather(conditions)

        forecast_names = {
            "clear": t("weather_fc_clear"), "fair": t("weather_fc_fair"),
            "improving": t("weather_fc_improving"), "stable": t("weather_fc_stable"),
            "deteriorating": t("weather_fc_deteriorating"), "rain_likely": t("weather_fc_rain"),
            "unsettled": t("weather_fc_unsettled"), "storm_likely": t("weather_fc_storm"),
            "no_data": t("weather_fc_no_data"), "unknown": t("weather_fc_unknown"),
        }

        pressure_str = f"{conditions['pressure_hpa']:.1f} hPa" if conditions.get("pressure_hpa") else "—"
        trend_str = {
            "rising": t("weather_trend_rising"),
            "falling": t("weather_trend_falling"),
            "stable": t("weather_trend_stable"),
        }.get(conditions.get("pressure_trend", "stable"), t("weather_trend_stable"))

        lines = [
            t("weather_header"),
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            t("weather_pressure_line", pressure=pressure_str, trend=trend_str),
            t("weather_forecast_line", forecast=forecast_names.get(prediction['forecast'], prediction['forecast'])),
            t("weather_confidence_line", pct=int(prediction['confidence'] * 100)),
        ]

        if conditions.get("temperature_c") is not None:
            lines.append(t("weather_temp_line", temp=conditions['temperature_c']))
        if conditions.get("humidity_pct") is not None:
            lines.append(t("weather_humidity_line", pct=conditions['humidity_pct']))

        lines.append(f"\n  💡 {prediction['advice']}")

        return "\n".join(lines)
