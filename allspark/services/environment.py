import logging

from allspark.core.i18n import t
from allspark.core.models import ResourceType

logger = logging.getLogger(__name__)


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
            result["recommendations"].append(t("env_rec_poor"))
        elif result["overall_score"] < 0.6:
            result["recommendations"].append(t("env_rec_fair"))
        else:
            result["recommendations"].append(t("env_rec_good"))

        if result["threats"]["level"] == "high":
            result["recommendations"].append(t("env_rec_high_threat"))

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
            prediction.get("severity", "normal")

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
                    result["details"] += " " + t("env_extreme_temp", temp=temp)
                elif temp < 0 or temp > 35:
                    result["score"] = max(0.1, result["score"] - 0.1)

        return result

    def _assess_terrain(self) -> dict:
        result = {
            "type": "unknown",
            "score": 0.5,
            "details": t("env_terrain_unknown"),
        }

        pois = self.db.get_all_pois()
        if pois:
            poi_types = {p.type for p in pois}
            if "water" in poi_types:
                result["score"] = min(1.0, result["score"] + 0.2)
                result["details"] = t("env_terrain_water")
            if "danger" in poi_types:
                result["score"] = max(0.1, result["score"] - 0.2)
                result["details"] += t("env_terrain_danger")
            if "shelter" in poi_types or "camp" in poi_types:
                result["score"] = min(1.0, result["score"] + 0.15)
                result["details"] += t("env_terrain_shelter")

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
                result["factors"].append(t("env_threat_power_critical"))
            elif power.estimated_remaining_hours < 24:
                result["level"] = "medium"
                result["score"] -= 0.15
                result["factors"].append(t("env_threat_power_low"))

        water = self.db.get_resource(ResourceType.WATER)
        if water and water.estimated_remaining_hours > 0:
            if water.estimated_remaining_hours < 24:
                result["level"] = "high"
                result["score"] -= 0.3
                result["factors"].append(t("env_threat_water_critical"))
            elif water.estimated_remaining_hours < 72:
                result["score"] -= 0.1
                result["factors"].append(t("env_threat_water_low"))

        if self.weather:
            conditions = self.weather.get_current_conditions()
            prediction = self.weather.predict_weather(conditions)
            if prediction.get("severity") == "severe":
                result["level"] = "high"
                result["score"] -= 0.2
                result["factors"].append(t("env_threat_weather"))

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
            result["items"].append(t("env_opp_power_ok"))

        knowledge_count = self.db.get_knowledge_count()
        if knowledge_count > 20:
            result["score"] += 0.1
            result["items"].append(t("env_opp_knowledge", count=knowledge_count))

        if self.survival:
            assessment = self.survival.assess()
            phase = assessment.get("phase", 0)
            if phase >= 1:
                result["items"].append(t("env_opp_stable"))

        pois = self.db.get_all_pois()
        if len(pois) > 3:
            result["score"] += 0.1
            result["items"].append(t("env_opp_pois", count=len(pois)))

        result["score"] = min(1.0, result["score"])
        return result

    def format_assessment(self, assessment: dict = None) -> str:
        if assessment is None:
            assessment = self.assess()

        score_pct = int(assessment["overall_score"] * 100)
        score_icon = "🟢" if score_pct >= 60 else "🟡" if score_pct >= 30 else "🔴"

        lines = [
            t("env_header"),
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            t("env_overall_score", icon=score_icon, pct=score_pct),
            "",
            t("env_climate_line", condition=assessment['climate']['condition'], pct=int(assessment['climate']['score'] * 100)),
            t("env_terrain_line", details=assessment['terrain']['details'], pct=int(assessment['terrain']['score'] * 100)),
            t("env_threat_line", level=assessment['threats']['level'], pct=int(assessment['threats']['score'] * 100)),
            t("env_opp_line", pct=int(assessment['opportunities']['score'] * 100)),
        ]

        if assessment["threats"]["factors"]:
            lines.append("")
            lines.append(t("env_threat_factors"))
            for f in assessment["threats"]["factors"]:
                lines.append(f"    - {f}")

        if assessment["opportunities"]["items"]:
            lines.append("")
            lines.append(t("env_opportunities"))
            for item in assessment["opportunities"]["items"]:
                lines.append(f"    + {item}")

        if assessment["recommendations"]:
            lines.append("")
            for r in assessment["recommendations"]:
                lines.append(f"  {r}")

        return "\n".join(lines)
