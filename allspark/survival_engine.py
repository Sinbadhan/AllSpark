from datetime import datetime
from typing import Optional

from allspark.database import Database
from allspark.models import (
    Resource, ResourceType, SurvivorState, OperatingMode
)
from allspark.config import PHASE_DESCRIPTIONS, PHASE_GOALS
from allspark.resource_manager import ResourceManager


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
            "phase_description": PHASE_DESCRIPTIONS.get(phase, "未知"),
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

        water_days = (water.estimated_remaining_hours / 24.0) if water else 0
        food_days = (food.estimated_remaining_hours / 24.0) if food else 0

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
            if r.type == ResourceType.WATER:
                days = r.estimated_remaining_hours / 24.0
                if days < 3:
                    bottlenecks.append(("水", days, "天"))
            elif r.type == ResourceType.FOOD:
                days = r.estimated_remaining_hours / 24.0
                if days < 5:
                    bottlenecks.append(("食物", days, "天"))
            elif r.type == ResourceType.POWER:
                hours = r.estimated_remaining_hours
                if hours < 24:
                    bottlenecks.append(("电力", hours, "小时"))
            elif r.type == ResourceType.FIRE:
                if r.current_amount < 10:
                    bottlenecks.append(("火源", r.current_amount, "次"))

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
            f"═══ 生存评估报告 ═══",
            f"当前阶段：{a['phase_description']}",
        ]

        if a["bottleneck"]:
            b = a["bottleneck"]
            lines.append(f"🚨 关键瓶颈：{b['resource']}（剩余 {b['remaining']:.1f}{b['unit']}）")

        if a["warnings"]:
            lines.append("")
            lines.append("⚠️ 警告：")
            for w in a["warnings"]:
                lines.append(f"  {w['message']}")

        lines.append("")
        lines.append(f"📋 当前任务数：{len(a['active_tasks'])}")

        mode, _ = self.resource_mgr.update_operating_mode()
        mode_names = {
            OperatingMode.PROACTIVE: "主动模式",
            OperatingMode.STANDARD: "标准模式",
            OperatingMode.ECONOMY: "节能模式",
            OperatingMode.HIBERNATION: "休眠模式",
            OperatingMode.RECOVERY: "恢复模式",
        }
        lines.append(f"🖥️ 运行模式：{mode_names.get(mode, mode.value)}")

        return "\n".join(lines)
