from datetime import datetime
from typing import Optional

from allspark.models import ResourceType


class EnvironmentAssessor:
    def __init__(self, db, weather=None, resource_mgr=None, survival=None):
        self.db = db
        self.weather = weather
        self.resource_mgr = resource_mgr
        self.survival = survival

    def assess(self) -> dict:
        result = {
            "climate": self._assess_climate(),
            "terrain": self._assess_terrain(),
            "threats": self._assess_threats(),
            "opportunities": self._assess_opportunities(),
            "overall_score": 0.0,
            "recommendations": [],
        }

        scores = []
        for dimension in ["climate", "terrain", "threats", "opportunities"]:
            score = result[dimension].get("score", 0.5)
            scores.append(score)

        result["overall_score"] = sum(scores) / len(scores) if scores else 0.5

        if result["overall_score"] < 0.3:
            result["recommendations"].append(
                "🚨 环境评估较差，建议优先保障基本生存需求，减少不必要的活动。"
            )
        elif result["overall_score"] < 0.6:
            result["recommendations"].append(
                "⚡ 环境一般，注意防范风险，合理分配资源。"
            )
        else:
            result["recommendations"].append(
                "✅ 环境尚可，可以安排探索和资源采集活动。"
            )

        if result["threats"]["level"] == "high":
            result["recommendations"].append(
                "⚠️ 存在高威胁因素，建议加强防御和警戒。"
            )

        return result

    def _assess_climate(self) -> dict:
        result = {
            "condition": "unknown",
            "score": 0.5,
            "details": "",
        }

        if self.weather:
            conditions = self.weather.get_current_conditions()
            prediction = self.weather.predict_weather(conditions)

            forecast = prediction.get("forecast", "unknown")
            severity = prediction.get("severity", "normal")

            climate_scores = {
                "clear": 0.9, "fair": 0.8, "improving": 0.7,
                "stable": 0.6, "deteriorating": 0.4,
                "unsettled": 0.3, "rain_likely": 0.2,
                "storm_likely": 0.1, "no_data": 0.5, "unknown": 0.5,
            }

            result["condition"] = forecast
            result["score"] = climate_scores.get(forecast, 0.5)
            result["details"] = prediction.get("advice", "")

            temp = conditions.get("temperature_c")
            if temp is not None:
                if temp < -10 or temp > 45:
                    result["score"] = max(0.1, result["score"] - 0.3)
                    result["details"] += f" 极端温度：{temp}°C"
                elif temp < 0 or temp > 35:
                    result["score"] = max(0.1, result["score"] - 0.1)

        return result

    def _assess_terrain(self) -> dict:
        result = {
            "type": "unknown",
            "score": 0.5,
            "details": "地形信息需要手动输入或通过GPS获取",
        }

        pois = self.db.get_all_pois()
        if pois:
            poi_types = {p.type for p in pois}
            if "water" in poi_types:
                result["score"] = min(1.0, result["score"] + 0.2)
                result["details"] = "附近有水源"
            if "danger" in poi_types:
                result["score"] = max(0.1, result["score"] - 0.2)
                result["details"] += "，存在危险区域"
            if "shelter" in poi_types or "camp" in poi_types:
                result["score"] = min(1.0, result["score"] + 0.15)
                result["details"] += "，有庇护所/营地"

        return result

    def _assess_threats(self) -> dict:
        result = {
            "level": "low",
            "score": 0.8,
            "factors": [],
        }

        power = self.db.get_resource(ResourceType.POWER)
        if power and power.estimated_remaining_hours > 0:
            if power.estimated_remaining_hours < 6:
                result["level"] = "high"
                result["score"] -= 0.3
                result["factors"].append("电力即将耗尽")
            elif power.estimated_remaining_hours < 24:
                result["level"] = "medium"
                result["score"] -= 0.15
                result["factors"].append("电力不足")

        water = self.db.get_resource(ResourceType.WATER)
        if water and water.estimated_remaining_hours > 0:
            if water.estimated_remaining_hours < 24:
                result["level"] = "high"
                result["score"] -= 0.3
                result["factors"].append("水源严重不足")
            elif water.estimated_remaining_hours < 72:
                result["score"] -= 0.1
                result["factors"].append("水源不足")

        if self.weather:
            conditions = self.weather.get_current_conditions()
            prediction = self.weather.predict_weather(conditions)
            if prediction.get("severity") == "severe":
                result["level"] = "high"
                result["score"] -= 0.2
                result["factors"].append("恶劣天气预警")

        result["score"] = max(0.0, min(1.0, result["score"]))
        return result

    def _assess_opportunities(self) -> dict:
        result = {
            "score": 0.5,
            "items": [],
        }

        state = self.db.get_operating_state()
        if state.mode in ("proactive", "standard"):
            result["score"] += 0.2
            result["items"].append("电力充足，可进行探索活动")

        knowledge_count = self.db.get_knowledge_count()
        if knowledge_count > 20:
            result["score"] += 0.1
            result["items"].append(f"知识库丰富（{knowledge_count}条）")

        if self.survival:
            assessment = self.survival.assess()
            phase = assessment.get("phase", 0)
            if phase >= 1:
                result["items"].append("基础生存稳定，可发展长期项目")

        pois = self.db.get_all_pois()
        if len(pois) > 3:
            result["score"] += 0.1
            result["items"].append(f"已发现{len(pois)}个地点")

        result["score"] = min(1.0, result["score"])
        return result

    def format_assessment(self, assessment: dict = None) -> str:
        if assessment is None:
            assessment = self.assess()

        score_pct = int(assessment["overall_score"] * 100)
        score_icon = "🟢" if score_pct >= 60 else "🟡" if score_pct >= 30 else "🔴"

        lines = [
            "🌍 环境评估",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"  {score_icon} 综合评分：{score_pct}%",
            "",
            f"  🌤️ 气候：{assessment['climate']['condition']} "
            f"({int(assessment['climate']['score'] * 100)}%)",
            f"  🏔️ 地形：{assessment['terrain']['details']} "
            f"({int(assessment['terrain']['score'] * 100)}%)",
            f"  ⚠️ 威胁等级：{assessment['threats']['level']} "
            f"({int(assessment['threats']['score'] * 100)}%)",
            f"  💡 机会：{int(assessment['opportunities']['score'] * 100)}%",
        ]

        if assessment["threats"]["factors"]:
            lines.append("")
            lines.append("  威胁因素：")
            for f in assessment["threats"]["factors"]:
                lines.append(f"    - {f}")

        if assessment["opportunities"]["items"]:
            lines.append("")
            lines.append("  机会：")
            for item in assessment["opportunities"]["items"]:
                lines.append(f"    + {item}")

        if assessment["recommendations"]:
            lines.append("")
            for r in assessment["recommendations"]:
                lines.append(f"  {r}")

        return "\n".join(lines)
