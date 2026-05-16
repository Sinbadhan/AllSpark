from datetime import datetime
from typing import Optional


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
            prediction["advice"] = "无法预测天气：缺少气压数据。请接入气压传感器或手动输入。"
            return prediction

        if pressure > 1020:
            if trend == "rising":
                prediction["forecast"] = "clear"
                prediction["confidence"] = 0.7
                prediction["advice"] = "高压上升，预计持续晴朗天气。适合外出活动和采集资源。"
            else:
                prediction["forecast"] = "fair"
                prediction["confidence"] = 0.6
                prediction["advice"] = "高压但趋于稳定，天气尚可，可安排室外活动。"

        elif pressure > 1000:
            if trend == "rising":
                prediction["forecast"] = "improving"
                prediction["confidence"] = 0.5
                prediction["advice"] = "气压正常且上升，天气趋于好转。"
            elif trend == "stable":
                prediction["forecast"] = "stable"
                prediction["confidence"] = 0.5
                prediction["advice"] = "气压稳定，天气将维持当前状况。"
            else:
                prediction["forecast"] = "deteriorating"
                prediction["confidence"] = 0.5
                prediction["advice"] = "气压正常但下降，天气可能转差。注意准备防雨措施。"

        elif pressure > 985:
            if trend == "falling":
                prediction["forecast"] = "rain_likely"
                prediction["confidence"] = 0.65
                prediction["severity"] = "moderate"
                prediction["advice"] = "气压较低且下降，近期可能降雨。建议：收集雨水、加固庇护所防水、减少外出。"
            else:
                prediction["forecast"] = "unsettled"
                prediction["confidence"] = 0.5
                prediction["advice"] = "气压偏低，天气不稳定。随时准备应对变化。"

        else:
            prediction["forecast"] = "storm_likely"
            prediction["confidence"] = 0.75
            prediction["severity"] = "severe"
            prediction["advice"] = "🚨 气压极低，暴风雨概率高！建议：立即加固庇护所、储存物资、避免外出。"

        if humidity is not None and humidity > 85 and trend == "falling":
            if prediction["severity"] == "normal":
                prediction["severity"] = "moderate"
            prediction["advice"] += " 高湿度+气压下降，降雨概率进一步提升。"

        if temp is not None and temp < 5:
            prediction["advice"] += " 注意：低温天气，做好防寒保暖。"

        return prediction

    def get_cloud_guide(self) -> str:
        return (
            "☁️ 云图指南（目测参考）：\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "  ☀️ 晴空无云 / 少量卷云 → 持续晴好\n"
            "  🌤️ 积云（棉花状）→ 白天晴，傍晚可能阵雨\n"
            "  ☁️ 层云（灰色薄层）→ 阴天，可能细雨\n"
            "  🌥️ 高积云（鱼鳞状）→ 天气转变信号\n"
            "  ⛈️ 积雨云（高耸黑色）→ 暴风雨即将来临！\n"
            "  🌫️ 层积云（低矮灰白）→ 毛毛雨或雾\n"
            "\n"
            "口诀：云变黑、云变低、风变大 → 赶紧避！"
        )

    def set_manual_pressure(self, pressure_hpa: float):
        if self.db:
            self.db.save_hardware_profile(
                "manual_pressure", str(pressure_hpa)
            )

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
        return "stable"

    def format_prediction(self, conditions: dict = None) -> str:
        conditions = conditions or self.get_current_conditions()
        prediction = self.predict_weather(conditions)

        forecast_names = {
            "clear": "☀️ 晴朗", "fair": "🌤️ 晴好",
            "improving": "📈 转好", "stable": "➡️ 稳定",
            "deteriorating": "📉 转差", "rain_likely": "🌧️ 可能降雨",
            "unsettled": "🌥️ 不稳定", "storm_likely": "⛈️ 可能暴风雨",
            "no_data": "❓ 无数据", "unknown": "❓ 未知",
        }

        pressure_str = f"{conditions['pressure_hpa']:.1f} hPa" if conditions.get("pressure_hpa") else "—"
        trend_str = {"rising": "↑ 上升", "falling": "↓ 下降", "stable": "→ 稳定"}.get(
            conditions.get("pressure_trend", "stable"), "→ 稳定"
        )

        lines = [
            "🌤️ 天气预测",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"  气压：{pressure_str} ({trend_str})",
            f"  预测：{forecast_names.get(prediction['forecast'], prediction['forecast'])}",
            f"  置信度：{int(prediction['confidence'] * 100)}%",
        ]

        if conditions.get("temperature_c") is not None:
            lines.append(f"  温度：{conditions['temperature_c']:.1f}°C")
        if conditions.get("humidity_pct") is not None:
            lines.append(f"  湿度：{conditions['humidity_pct']:.0f}%")

        lines.append(f"\n  💡 {prediction['advice']}")

        return "\n".join(lines)
