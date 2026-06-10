from typing import Optional

from allspark.core.database import Database
from allspark.core.i18n import t
from allspark.core.models import OperatingMode, Resource, ResourceType
from allspark.services.resource_manager import ResourceManager


class SurvivalAssessmentEngine:
    def __init__(self, db: Database, resource_mgr: ResourceManager):
        self.db = db
        self.resource_mgr = resource_mgr

    def assess(self) -> dict:
        resources = self.resource_mgr.get_all_resources()
        warnings = self.resource_mgr.check_warnings()
        survivor = self.db.get_survivor_state()
        phase = self._determine_phase(resources, survivor)
        bottleneck = self._identify_bottleneck(resources)
        active_tasks = self.db.get_active_tasks()

        return {
            "phase": phase,
            "phase_description": t(f"phase_desc_{phase}"),
            "resources": resources,
            "warnings": warnings,
            "bottleneck": bottleneck,
            "survivor_state": survivor,
            "active_tasks": active_tasks,
        }

    def _determine_phase(self, resources: list[Resource],
                         survivor: dict) -> int:
        water = next((r for r in resources if r.type == ResourceType.WATER), None)
        food = next((r for r in resources if r.type == ResourceType.FOOD), None)
        fire = next((r for r in resources if r.type == ResourceType.FIRE), None)

        water_configured = water and self.resource_mgr.is_configured(water)
        food_configured = food and self.resource_mgr.is_configured(food)
        if not water_configured and not food_configured:
            return 1

        water_days = (water.estimated_remaining_hours / 24.0) if water_configured else float("inf")
        food_days = (food.estimated_remaining_hours / 24.0) if food_configured else float("inf")

        if water_days < 3 or food_days < 2:
            return 0
        if water_days < 14 or food_days < 7 or (fire and fire.current_amount < 5):
            return 1
        if water_days < 180 or food_days < 90:
            return 2
        if water_days < 1800 or food_days < 900:
            return 3
        return 4

    def _identify_bottleneck(self, resources: list[Resource]) -> Optional[dict]:
        bottlenecks = []
        for r in resources:
            if not self.resource_mgr.is_configured(r):
                continue
            if r.type == ResourceType.WATER:
                days = r.estimated_remaining_hours / 24.0
                if days < 3:
                    bottlenecks.append((t("resource_water"), days, t("res_unit_days", days=days).split()[0] if days < 1 else "d"))
            elif r.type == ResourceType.FOOD:
                days = r.estimated_remaining_hours / 24.0
                if days < 5:
                    bottlenecks.append((t("resource_food"), days, "d"))
            elif r.type == ResourceType.POWER:
                hours = r.estimated_remaining_hours
                if hours < 24:
                    bottlenecks.append((t("resource_power"), hours, "h"))
            elif r.type == ResourceType.FIRE:
                if r.current_amount < 10:
                    bottlenecks.append((t("resource_fire"), r.current_amount, ""))

        if not bottlenecks:
            return None

        bottlenecks.sort(key=lambda x: x[1])
        return {
            "resource": bottlenecks[0][0],
            "remaining": bottlenecks[0][1],
            "unit": bottlenecks[0][2],
            "all_bottlenecks": bottlenecks
        }

    def get_assessment_summary(self) -> str:
        a = self.assess()
        lines = [
            f"═══ {t('assessment_title')} ═══",
            f"{t('phase_desc_' + str(a['phase']))}",
        ]

        if a["bottleneck"]:
            b = a["bottleneck"]
            lines.append(f"{t('bottleneck_label')}: {b['resource']}({b['remaining']:.1f}{b['unit']})")

        if a["warnings"]:
            lines.append("")
            lines.append(t("warnings_label"))
            for w in a["warnings"]:
                lines.append(f"  {w['message']}")

        lines.append("")
        lines.append(f"{t('task_title')}: {len(a['active_tasks'])}")

        mode, _ = self.resource_mgr.update_operating_mode()
        mode_names = {
            OperatingMode.PROACTIVE: t("mode_proactive"),
            OperatingMode.STANDARD: t("mode_standard"),
            OperatingMode.ECONOMY: t("mode_economy"),
            OperatingMode.HIBERNATION: t("mode_hibernation"),
            OperatingMode.RECOVERY: t("mode_recovery"),
        }
        lines.append(f"{t('operating_mode_label', mode=mode_names.get(mode, mode.value))}")

        return "\n".join(lines)
