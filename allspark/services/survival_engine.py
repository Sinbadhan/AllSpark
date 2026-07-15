from datetime import datetime, timezone
from typing import Optional

from allspark.core.database import Database
from allspark.core.i18n import t
from allspark.core.models import OperatingMode, Resource, ResourceType
from allspark.services.resource_manager import ResourceManager


class SurvivalAssessmentEngine:
    _CRITICAL_PHASE_RESOURCES = (ResourceType.WATER, ResourceType.FOOD)
    def __init__(self, db: Database, resource_mgr: ResourceManager):
        self.db = db
        self.resource_mgr = resource_mgr

    def assess(self) -> dict:
        resources = self.resource_mgr.get_all_resources()
        warnings = self.resource_mgr.check_warnings()
        survivor = self.db.get_survivor_state()
        snapshot_now = self._now_utc()
        missing_fields, stale_fields = self._phase_evidence_gaps(
            resources, now=snapshot_now
        )
        phase = (
            None
            if missing_fields or stale_fields
            else self._determine_phase(resources, survivor, now=snapshot_now)
        )
        phase_status = "known" if phase is not None else "unknown"
        bottleneck = self._identify_bottleneck(
            resources, stale_fields=stale_fields, now=snapshot_now
        )
        active_tasks = self.db.get_active_tasks()

        return {
            "phase": phase,
            "phase_status": phase_status,
            "phase_description": t(
                f"phase_desc_{phase}" if phase is not None else "phase_desc_unknown"
            ),
            "missing_fields": missing_fields,
            "stale_fields": stale_fields,
            "resources": resources,
            "warnings": warnings,
            "bottleneck": bottleneck,
            "survivor_state": survivor,
            "active_tasks": active_tasks,
        }

    def _phase_evidence_gaps(
        self, resources: list[Resource], *, now: datetime
    ) -> tuple[list[str], list[str]]:
        by_type = {resource.type: resource for resource in resources}
        missing_fields: list[str] = []
        stale_fields: list[str] = []
        for resource_type in self._CRITICAL_PHASE_RESOURCES:
            prefix = resource_type.value
            resource = by_type.get(resource_type)
            if resource is None:
                missing_fields.extend(
                    f"{prefix}.{field}"
                    for field in ("amount", "consumption", "intake", "rate_basis")
                )
                stale_fields.append(f"{prefix}.as_of")
                continue
            if not resource.amount_known:
                missing_fields.append(f"{prefix}.amount")
            if not resource.consumption_known:
                missing_fields.append(f"{prefix}.consumption")
            if not resource.intake_known:
                missing_fields.append(f"{prefix}.intake")
            if resource.rate_basis != "group_total":
                missing_fields.append(f"{prefix}.rate_basis")
            if not self._snapshot_is_current(resource.as_of, now=now):
                stale_fields.append(f"{prefix}.as_of")
        return missing_fields, stale_fields

    @classmethod
    def _snapshot_is_current(cls, value: str, *, now: datetime) -> bool:
        probe = Resource(
            type=ResourceType.WATER, current_amount=0, unit="L", as_of=value
        )
        return ResourceManager.is_snapshot_current(probe, now=now)

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    def _determine_phase(
        self, resources: list[Resource], survivor: dict, *, now: datetime
    ) -> int:
        water = next((r for r in resources if r.type == ResourceType.WATER), None)
        food = next((r for r in resources if r.type == ResourceType.FOOD), None)
        fire = next((r for r in resources if r.type == ResourceType.FIRE), None)

        assert water is not None and food is not None
        water_days = (
            water.estimated_remaining_hours / 24.0
            if water.estimated_remaining_hours >= 0
            else float("inf")
        )
        food_days = (
            food.estimated_remaining_hours / 24.0
            if food.estimated_remaining_hours >= 0
            else float("inf")
        )

        if water_days < 3 or food_days < 2:
            return 0
        fire_low = bool(
            fire
            and self.resource_mgr.is_configured(fire)
            and self.resource_mgr.is_snapshot_current(fire, now=now)
            and fire.current_amount < 5
        )
        if water_days < 14 or food_days < 7 or fire_low:
            return 1
        if water_days < 180 or food_days < 90:
            return 2
        if water_days < 1800 or food_days < 900:
            return 3
        return 4

    def _identify_bottleneck(
        self,
        resources: list[Resource],
        *,
        stale_fields: list[str] | None = None,
        now: datetime,
    ) -> Optional[dict]:
        stale_resources = {
            field.split(".", 1)[0] for field in (stale_fields or [])
        }
        bottlenecks = []
        for r in resources:
            if r.type.value in stale_resources:
                continue
            if not self._snapshot_is_current(r.as_of, now=now):
                continue
            if not self.resource_mgr.is_configured(r):
                continue
            if r.type == ResourceType.WATER:
                if not self.resource_mgr.has_complete_rate_data(r):
                    continue
                days = r.estimated_remaining_hours / 24.0 if r.estimated_remaining_hours >= 0 else float("inf")
                if days < 3:
                    bottlenecks.append((t("resource_water"), days, t("res_unit_days", days=days).split()[0] if days < 1 else "d"))
            elif r.type == ResourceType.FOOD:
                if not self.resource_mgr.has_complete_rate_data(r):
                    continue
                days = r.estimated_remaining_hours / 24.0 if r.estimated_remaining_hours >= 0 else float("inf")
                if days < 5:
                    bottlenecks.append((t("resource_food"), days, "d"))
            elif r.type == ResourceType.POWER:
                if not self.resource_mgr.has_complete_rate_data(r):
                    continue
                hours = r.estimated_remaining_hours
                if hours >= 0 and hours < 24:
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
            a["phase_description"],
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
