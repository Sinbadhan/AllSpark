from datetime import datetime
from typing import Optional

from allspark.models import (
    Resource, ResourceType, OperatingMode, OperatingState
)
from allspark.config import (
    POWER_MODE_THRESHOLDS, POWER_CONSUMPTION_WATTS,
    RESOURCE_WARNING_THRESHOLDS
)
from allspark.database import Database
from allspark.i18n import t


class ResourceManager:
    def __init__(self, db: Database):
        self.db = db

    def init_defaults(self):
        for rtype, defaults in _DEFAULT_RESOURCES.items():
            existing = self.db.get_resource(rtype)
            if existing is None:
                self.db.upsert_resource(defaults)
        state = self.db.get_operating_state()
        if not state.last_mode_change:
            self.db.save_operating_state(state)

    def get_all_resources(self) -> list[Resource]:
        return self.db.get_all_resources()

    def update_resource(self, rtype: ResourceType, amount: float,
                        consumption: Optional[float] = None,
                        intake: Optional[float] = None):
        r = self.db.get_resource(rtype)
        if r is None:
            return
        r.current_amount = amount
        if consumption is not None:
            r.daily_consumption = consumption
        if intake is not None:
            r.daily_intake = intake
        r.estimated_remaining_hours = self._estimate_remaining(r)
        self.db.upsert_resource(r)

    def consume_resource(self, rtype: ResourceType, amount: float):
        r = self.db.get_resource(rtype)
        if r is None:
            return
        r.current_amount = max(0, r.current_amount - amount)
        r.estimated_remaining_hours = self._estimate_remaining(r)
        self.db.upsert_resource(r)

    def _estimate_remaining(self, r: Resource) -> float:
        if r.type == ResourceType.POWER:
            if r.daily_consumption <= r.daily_intake:
                return 9999.0
            net_hourly = (r.daily_consumption - r.daily_intake) / 24.0
            if net_hourly <= 0:
                return 9999.0
            return r.current_amount / net_hourly
        elif r.type in (ResourceType.WATER, ResourceType.FOOD):
            if r.daily_consumption <= 0:
                return 9999.0
            return (r.current_amount / r.daily_consumption) * 24.0
        elif r.type == ResourceType.FIRE:
            if r.daily_consumption <= 0:
                return 9999.0
            return r.current_amount * 24.0
        return 0.0

    def get_operating_mode(self) -> OperatingMode:
        state = self.db.get_operating_state()
        return OperatingMode(state.mode)

    def determine_operating_mode(self) -> OperatingMode:
        power = self.db.get_resource(ResourceType.POWER)
        if power is None:
            return OperatingMode.STANDARD
        hours = power.estimated_remaining_hours
        for mode in [OperatingMode.PROACTIVE, OperatingMode.STANDARD,
                      OperatingMode.ECONOMY, OperatingMode.HIBERNATION]:
            if hours >= POWER_MODE_THRESHOLDS[mode]:
                return mode
        return OperatingMode.HIBERNATION

    def update_operating_mode(self) -> tuple[OperatingMode, bool]:
        new_mode = self.determine_operating_mode()
        state = self.db.get_operating_state()
        old_mode = OperatingMode(state.mode)
        changed = new_mode != old_mode
        if changed:
            state.mode = new_mode.value
            state.power_remaining_hours = self.db.get_resource(
                ResourceType.POWER
            ).estimated_remaining_hours if self.db.get_resource(ResourceType.POWER) else 0
            state.last_mode_change = datetime.now().isoformat()
            self.db.save_operating_state(state)
        return new_mode, changed

    def check_warnings(self) -> list[dict]:
        warnings = []
        power = self.db.get_resource(ResourceType.POWER)
        if power:
            hours = power.estimated_remaining_hours
            thresh = RESOURCE_WARNING_THRESHOLDS["power"]
            if hours < thresh["critical_hours"]:
                warnings.append({
                    "resource": t("resource_power"), "level": "critical",
                    "message": t("warning_power_critical", hours=hours),
                    "hours_remaining": hours
                })
            elif hours < thresh["warning_hours"]:
                warnings.append({
                    "resource": t("resource_power"), "level": "warning",
                    "message": t("warning_power_low", hours=hours),
                    "hours_remaining": hours
                })

        water = self.db.get_resource(ResourceType.WATER)
        if water:
            days = water.estimated_remaining_hours / 24.0
            thresh = RESOURCE_WARNING_THRESHOLDS["water"]
            if days < thresh["critical_days"]:
                warnings.append({
                    "resource": t("resource_water"), "level": "critical",
                    "message": t("warning_water_critical", days=days),
                })
            elif days < thresh["warning_days"]:
                warnings.append({
                    "resource": t("resource_water"), "level": "warning",
                    "message": t("warning_water_low", days=days),
                })

        food = self.db.get_resource(ResourceType.FOOD)
        if food:
            days = food.estimated_remaining_hours / 24.0
            thresh = RESOURCE_WARNING_THRESHOLDS["food"]
            if days < thresh["critical_days"]:
                warnings.append({
                    "resource": t("resource_food"), "level": "critical",
                    "message": t("warning_food_critical", days=days),
                })
            elif days < thresh["warning_days"]:
                warnings.append({
                    "resource": t("resource_food"), "level": "warning",
                    "message": t("warning_food_low", days=days),
                })

        fire = self.db.get_resource(ResourceType.FIRE)
        if fire:
            thresh = RESOURCE_WARNING_THRESHOLDS["fire"]
            if fire.current_amount < thresh["critical_uses"]:
                warnings.append({
                    "resource": t("resource_fire"), "level": "critical",
                    "message": t("warning_fire_critical", count=fire.current_amount),
                })
            elif fire.current_amount < thresh["warning_uses"]:
                warnings.append({
                    "resource": t("resource_fire"), "level": "warning",
                    "message": t("warning_fire_low", count=fire.current_amount),
                })

        storage = self.db.get_resource(ResourceType.STORAGE)
        if storage:
            total = storage.daily_consumption
            used = storage.daily_intake
            if total > 0:
                pct = (1 - used / total) * 100
                thresh = RESOURCE_WARNING_THRESHOLDS["storage"]
                if pct < thresh["critical_percent"]:
                    warnings.append({
                        "resource": t("resource_storage"), "level": "critical",
                        "message": t("warning_storage_critical", pct=pct),
                    })
                elif pct < thresh["warning_percent"]:
                    warnings.append({
                        "resource": t("resource_storage"), "level": "warning",
                        "message": t("warning_storage_low", pct=pct),
                    })
        return warnings

    def get_power_savings_advice(self, mode: OperatingMode) -> list[str]:
        advice = []
        if mode == OperatingMode.ECONOMY:
            advice = [
                "已自动切换至节能模式，LLM 已禁用",
                "仅规则引擎运行，回答生存相关问题",
                "建议：检查太阳能板/手摇发电机是否可用",
                "建议：评估附近是否有可获取电池的废墟",
                "如果在 12h 内无法补充电力，将进入休眠模式",
            ]
        elif mode == OperatingMode.HIBERNATION:
            advice = [
                "🚨 已进入休眠模式！",
                "仅维持核心数据库运行",
                "每次唤醒只回答生存相关问题",
                "请尽快补充电力！",
            ]
        elif mode == OperatingMode.STANDARD:
            advice = [
                "已切换至标准模式",
                "LLM 降载运行",
                "后台维护任务已暂停",
            ]
        return advice

    def get_resource_summary(self) -> str:
        resources = self.get_all_resources()
        state = self.db.get_operating_state()
        mode = OperatingMode(state.mode)
        mode_names = {
            OperatingMode.PROACTIVE: "主动模式",
            OperatingMode.STANDARD: "标准模式",
            OperatingMode.ECONOMY: "节能模式",
            OperatingMode.HIBERNATION: "休眠模式",
            OperatingMode.RECOVERY: "恢复模式",
        }
        lines = [
            f"运行模式：{mode_names.get(mode, mode.value)}",
            "",
        ]
        for r in resources:
            if r.type == ResourceType.POWER:
                lines.append(f"⚡ 电力：{r.current_amount:.0f}Wh | 预计续航 {r.estimated_remaining_hours:.1f}h | 消耗 {r.daily_consumption:.0f}Wh/天 | 充入 {r.daily_intake:.0f}Wh/天")
            elif r.type == ResourceType.WATER:
                days = r.estimated_remaining_hours / 24.0
                lines.append(f"💧 饮水：{r.current_amount:.1f}L | 预计 {days:.1f}天 | 消耗 {r.daily_consumption:.1f}L/天")
            elif r.type == ResourceType.FOOD:
                days = r.estimated_remaining_hours / 24.0
                lines.append(f"🍞 食物：{r.current_amount:.0f}kcal | 预计 {days:.1f}天 | 消耗 {r.daily_consumption:.0f}kcal/天")
            elif r.type == ResourceType.FIRE:
                lines.append(f"🔥 火源：{r.current_amount:.0f}次 | 消耗 {r.daily_consumption:.0f}次/天")
            elif r.type == ResourceType.STORAGE:
                total = r.daily_consumption
                used = r.daily_intake
                pct = ((total - used) / total * 100) if total > 0 else 0
                lines.append(f"💾 存储：{used:.0f}/{total:.0f}GB | 剩余 {pct:.1f}%")
        lines.append("\n⚠️ 以上数据为估算值，仅供参考。可手动输入校正。")
        return "\n".join(lines)


_DEFAULT_RESOURCES = {
    ResourceType.POWER: Resource(
        type=ResourceType.POWER,
        current_amount=37.0,
        unit="Wh",
        daily_consumption=120.0,
        daily_intake=0.0,
        estimated_remaining_hours=7.4,
        last_updated=""
    ),
    ResourceType.WATER: Resource(
        type=ResourceType.WATER,
        current_amount=5.0,
        unit="L",
        daily_consumption=2.0,
        daily_intake=0.0,
        estimated_remaining_hours=60.0,
        last_updated=""
    ),
    ResourceType.FOOD: Resource(
        type=ResourceType.FOOD,
        current_amount=6000.0,
        unit="kcal",
        daily_consumption=2000.0,
        daily_intake=0.0,
        estimated_remaining_hours=72.0,
        last_updated=""
    ),
    ResourceType.FIRE: Resource(
        type=ResourceType.FIRE,
        current_amount=20.0,
        unit="次",
        daily_consumption=3.0,
        daily_intake=0.0,
        estimated_remaining_hours=160.0,
        last_updated=""
    ),
    ResourceType.STORAGE: Resource(
        type=ResourceType.STORAGE,
        current_amount=0.0,
        unit="GB",
        daily_consumption=16.0,
        daily_intake=2.0,
        estimated_remaining_hours=0.0,
        last_updated=""
    ),
}
