import json
import logging
from datetime import datetime, timedelta
from typing import Any

from allspark.core.i18n import t
from allspark.core.models import Resource, ResourceType

logger = logging.getLogger(__name__)

_CLIMATE_MAX_AGE = timedelta(hours=6)
_RESOURCE_MAX_AGE = timedelta(hours=24)
_REQUIRED_RESOURCES = (
    ResourceType.POWER,
    ResourceType.WATER,
    ResourceType.FOOD,
)


class EnvironmentAssessor:
    def __init__(self, db, weather=None, resource_mgr=None, survival=None):
        self.db = db
        self.weather = weather
        self.resource_mgr = resource_mgr
        self.survival = survival

    def assess(self) -> dict:
        checked_at = datetime.now().isoformat()
        climate = self._assess_climate()
        terrain = self._assess_terrain()
        resource_evidence, resource_source = self._assess_resources()

        available = {
            "climate": bool(climate["available"]),
            "terrain": bool(terrain["available"]),
            "resources": all(
                resource_evidence[rtype.value]["status"] != "unknown"
                and not resource_evidence[rtype.value]["stale"]
                for rtype in _REQUIRED_RESOURCES
            ),
        }
        missing = [name for name, present in available.items() if not present]
        complete = not missing
        threats = self._assess_threats(complete, resource_evidence, climate)
        opportunities = self._assess_opportunities(complete, resource_evidence)

        result: dict[str, Any] = {
            "status": "assessed" if complete else "unknown",
            "climate": climate,
            "terrain": terrain,
            "threats": threats,
            "opportunities": opportunities,
            "resource_evidence": resource_evidence,
            "overall_score": None,
            "recommendations": [],
            "completeness": {
                "complete": complete,
                "ratio": round(sum(available.values()) / len(available), 2),
                "available": available,
                "missing": missing,
                "checked_at": checked_at,
            },
            "sources": {
                "climate": self._source_view(climate),
                "terrain": self._source_view(terrain),
                "resources": resource_source,
            },
        }

        if not complete:
            result["recommendations"].append(t("env_rec_insufficient"))
            return result

        scores = [
            climate["score"],
            terrain["score"],
            threats["score"],
            opportunities["score"],
        ]
        result["overall_score"] = sum(scores) / len(scores)
        if result["overall_score"] < 0.3:
            result["recommendations"].append(t("env_rec_poor"))
        elif result["overall_score"] < 0.6:
            result["recommendations"].append(t("env_rec_fair"))
        else:
            result["recommendations"].append(t("env_rec_good"))
        if threats["level"] == "high":
            result["recommendations"].append(t("env_rec_high_threat"))
        return result

    def _assess_climate(self) -> dict:
        result: dict[str, Any] = {
            "condition": "unknown",
            "score": None,
            "details": t("env_climate_unknown"),
            "available": False,
            "source": "unknown",
            "observed_at": None,
            "stale": True,
        }
        if not self.weather:
            return result

        conditions = self.weather.get_current_conditions()
        prediction = self.weather.predict_weather(conditions)
        forecast = prediction.get("forecast", "unknown")
        observed_at = conditions.get("observed_at")
        stale = bool(
            conditions.get("stale", self._is_stale(observed_at, _CLIMATE_MAX_AGE))
        )
        result.update(
            {
                "condition": forecast,
                "details": prediction.get("advice", ""),
                "source": conditions.get("source") or "unknown",
                "observed_at": observed_at,
                "stale": stale,
            }
        )
        if forecast in {"unknown", "no_data"} or stale:
            return result

        climate_scores = {
            "clear": 0.9,
            "fair": 0.8,
            "improving": 0.7,
            "stable": 0.6,
            "deteriorating": 0.4,
            "unsettled": 0.3,
            "rain_likely": 0.2,
            "storm_likely": 0.1,
        }
        if forecast not in climate_scores:
            return result
        result["score"] = climate_scores[forecast]
        result["available"] = True

        temp = conditions.get("temperature_c")
        if temp is not None:
            if temp < -10 or temp > 45:
                result["score"] = max(0.1, result["score"] - 0.3)
                result["details"] += " " + t("env_extreme_temp", temp=temp)
            elif temp < 0 or temp > 35:
                result["score"] = max(0.1, result["score"] - 0.1)
        return result

    def _assess_terrain(self) -> dict:
        result: dict[str, Any] = {
            "type": "unknown",
            "score": None,
            "details": t("env_terrain_unknown"),
            "available": False,
            "source": "unknown",
            "observed_at": None,
            "stale": False,
        }
        pois = self.db.get_all_pois()
        if pois:
            result.update(
                {
                    "type": "poi",
                    "score": 0.5,
                    "details": "",
                    "available": True,
                    "source": "poi",
                    "observed_at": max(
                        (poi.discovered_at for poi in pois if poi.discovered_at),
                        default=None,
                    ),
                }
            )
            poi_types = {poi.type for poi in pois}
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

        row = self.db.conn.execute(
            "SELECT value FROM hardware_profile WHERE key='last_gps_position'"
        ).fetchone()
        if not row:
            return result
        try:
            position = json.loads(row["value"])
            observed_at = position.get("timestamp")
            stale = self._is_stale(observed_at, _RESOURCE_MAX_AGE)
            if "lat" in position and "lon" in position and not stale:
                result.update(
                    {
                        "type": "gps",
                        "score": 0.5,
                        "details": t("env_terrain_gps"),
                        "available": True,
                        "source": position.get("source") or "gps",
                        "observed_at": observed_at,
                        "stale": False,
                    }
                )
            else:
                result.update(
                    {
                        "source": position.get("source") or "gps",
                        "observed_at": observed_at,
                        "stale": stale,
                    }
                )
        except (json.JSONDecodeError, TypeError):
            logger.warning("Invalid last_gps_position while assessing terrain")
        return result

    def _assess_resources(self) -> tuple[dict[str, dict], dict]:
        resources = {resource.type: resource for resource in self.db.get_all_resources()}
        evidence: dict[str, dict] = {}
        observed_values: list[str] = []
        for resource_type in _REQUIRED_RESOURCES:
            resource = resources.get(resource_type)
            status = self._resource_status(resource)
            observed_at = resource.last_updated if resource else None
            stale = status != "unknown" and self._is_stale(
                observed_at, _RESOURCE_MAX_AGE
            )
            evidence[resource_type.value] = {
                "status": status,
                "observed_at": observed_at,
                "stale": stale,
                "source": "database" if status != "unknown" else "unknown",
            }
            if status != "unknown" and observed_at:
                observed_values.append(observed_at)
        known_count = sum(
            item["status"] != "unknown" for item in evidence.values()
        )
        source = (
            "database"
            if known_count == len(_REQUIRED_RESOURCES)
            else "database_partial"
            if known_count
            else "unknown"
        )
        return evidence, {
            "source": source,
            "observed_at": max(observed_values, default=None),
            "stale": any(
                item["stale"]
                for item in evidence.values()
                if item["status"] != "unknown"
            ),
        }

    def _resource_status(self, resource: Resource | None) -> str:
        if resource is None or not self._is_configured(resource):
            return "unknown"
        if resource.current_amount <= 0:
            return "zero"
        if resource.estimated_remaining_hours < 0:
            return "sustained"
        return "healthy"

    def _is_configured(self, resource: Resource) -> bool:
        if self.resource_mgr:
            return bool(self.resource_mgr.is_configured(resource))
        return not (
            resource.current_amount == 0
            and resource.daily_consumption == 0
            and resource.daily_intake == 0
        )

    def _assess_threats(
        self,
        inputs_complete: bool,
        resource_evidence: dict[str, dict],
        climate: dict,
    ) -> dict:
        result: dict[str, Any] = {
            "level": "low" if inputs_complete else "unknown",
            "score": 0.8 if inputs_complete else None,
            "factors": [],
        }

        def register(level: str, penalty: float, message: str) -> None:
            if level == "high" or result["level"] in {"low", "unknown"}:
                result["level"] = level
            if result["score"] is not None:
                result["score"] -= penalty
            result["factors"].append(message)

        power = self.db.get_resource(ResourceType.POWER)
        water = self.db.get_resource(ResourceType.WATER)
        food = self.db.get_resource(ResourceType.FOOD)
        power_current = self._is_current_resource(
            resource_evidence[ResourceType.POWER.value]
        )
        water_current = self._is_current_resource(
            resource_evidence[ResourceType.WATER.value]
        )
        food_current = self._is_current_resource(
            resource_evidence[ResourceType.FOOD.value]
        )

        if power_current and power and (
            power.current_amount <= 0 or 0 <= power.estimated_remaining_hours < 6
        ):
            register("high", 0.3, t("env_threat_power_critical"))
        elif power_current and power and 0 <= power.estimated_remaining_hours < 24:
            register("medium", 0.15, t("env_threat_power_low"))

        if water_current and water and (
            water.current_amount <= 0 or 0 <= water.estimated_remaining_hours < 24
        ):
            register("high", 0.3, t("env_threat_water_critical"))
        elif water_current and water and 0 <= water.estimated_remaining_hours < 72:
            register("medium", 0.1, t("env_threat_water_low"))

        if food_current and food and food.current_amount <= 0:
            register("high", 0.2, t("env_threat_food_critical"))

        if self.weather and climate["available"]:
            conditions = self.weather.get_current_conditions()
            prediction = self.weather.predict_weather(conditions)
            if prediction.get("severity") == "severe":
                register("high", 0.2, t("env_threat_weather"))
        if result["score"] is not None:
            result["score"] = max(0.0, min(1.0, float(result["score"])))
        return result

    @staticmethod
    def _is_current_resource(evidence: dict) -> bool:
        return evidence["status"] != "unknown" and not evidence["stale"]

    def _assess_opportunities(
        self, inputs_complete: bool, resource_evidence: dict[str, dict]
    ) -> dict:
        if not inputs_complete:
            return {"score": None, "items": []}
        result: dict[str, Any] = {"score": 0.5, "items": []}
        power = self.db.get_resource(ResourceType.POWER)
        power_status = resource_evidence[ResourceType.POWER.value]["status"]
        if power and (
            power_status == "sustained"
            or (
                power_status == "healthy"
                and power.estimated_remaining_hours >= 24
            )
        ):
            result["score"] += 0.2
            result["items"].append(t("env_opp_power_ok"))

        knowledge_count = self.db.get_knowledge_count()
        if knowledge_count > 20:
            result["score"] += 0.1
            result["items"].append(t("env_opp_knowledge", count=knowledge_count))
        if self.survival and self.survival.assess().get("phase", 0) >= 2:
            result["items"].append(t("env_opp_stable"))
        pois = self.db.get_all_pois()
        if len(pois) > 3:
            result["score"] += 0.1
            result["items"].append(t("env_opp_pois", count=len(pois)))
        result["score"] = min(1.0, float(result["score"]))
        return result

    def format_assessment(self, assessment: dict | None = None) -> str:
        assessment = assessment or self.assess()
        overall_score = assessment.get("overall_score")
        if isinstance(overall_score, (int, float)):
            score_pct = int(overall_score * 100)
            score_icon = "🟢" if score_pct >= 60 else "🟡" if score_pct >= 30 else "🔴"
            score_line = t("env_overall_score", icon=score_icon, pct=score_pct)
        else:
            score_line = t("env_overall_unknown")

        lines = [
            t("env_header"),
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            score_line,
            t(
                "env_completeness_line",
                pct=int(assessment["completeness"]["ratio"] * 100),
                missing=", ".join(
                    t(f"env_dimension_{name}")
                    for name in assessment["completeness"]["missing"]
                )
                or "-",
            ),
        ]
        for name, source in assessment["sources"].items():
            source_name = source.get("source") or "unknown"
            source_key = f"env_source_{source_name}"
            translated_source = t(source_key)
            if translated_source == source_key:
                translated_source = source_name
            lines.append(
                t(
                    "env_source_line",
                    dimension=t(f"env_dimension_{name}"),
                    source=translated_source,
                    observed_at=source.get("observed_at")
                    or t("env_source_time_unknown"),
                    freshness=t("env_source_stale") if source.get("stale") else "",
                )
            )
        if assessment["threats"]["factors"]:
            lines.append(t("env_threat_factors"))
            lines.extend(f"    - {factor}" for factor in assessment["threats"]["factors"])
        if assessment["opportunities"]["items"]:
            lines.append(t("env_opportunities"))
            lines.extend(f"    + {item}" for item in assessment["opportunities"]["items"])
        lines.extend(f"  {recommendation}" for recommendation in assessment["recommendations"])
        return "\n".join(lines)

    @staticmethod
    def _source_view(dimension: dict) -> dict:
        return {
            "source": dimension.get("source", "unknown"),
            "observed_at": dimension.get("observed_at"),
            "stale": bool(dimension.get("stale", False)),
        }

    @staticmethod
    def _is_stale(observed_at: str | None, max_age: timedelta) -> bool:
        if not observed_at:
            return True
        try:
            observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
            now = datetime.now(observed.tzinfo) if observed.tzinfo else datetime.now()
            return now - observed > max_age
        except (TypeError, ValueError):
            return True
