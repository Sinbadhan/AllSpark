import logging
import math
from datetime import datetime
from typing import Optional

from allspark.core.config import POWER_MODE_THRESHOLDS, RESOURCE_WARNING_THRESHOLDS
from allspark.core.database import Database
from allspark.core.i18n import t
from allspark.core.models import OperatingMode, Resource, ResourceType

logger = logging.getLogger(__name__)


class ResourceValidationError(ValueError):
    """Raised before an invalid resource value can reach persistence."""

    def __init__(self, field: str, reason: str):
        self.field = field
        self.reason = reason
        super().__init__(f"{field}: {reason}")


class ResourceManager:
    # Technical safety ceiling: rejects overflow/abuse without constraining any
    # plausible single-device or community inventory. Product-specific soft
    # ranges and confirmation belong to the input contract (SHA-237).
    MAX_RESOURCE_VALUE = 1_000_000_000_000.0

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

    def is_configured(self, r: Resource) -> bool:
        return not (r.current_amount == 0 and r.daily_consumption == 0 and r.daily_intake == 0)

    def has_remaining_estimate(self, r: Resource) -> bool:
        if not self.is_configured(r):
            return False
        if r.type == ResourceType.POWER:
            return r.daily_consumption > r.daily_intake
        if r.type in (ResourceType.WATER, ResourceType.FOOD, ResourceType.FIRE):
            return r.daily_consumption > 0
        return False

    def update_resource(self, rtype: ResourceType, amount: float,
                        consumption: Optional[float] = None,
                        intake: Optional[float] = None):
        amount = self._validate_value("amount", amount)
        if consumption is not None:
            consumption = self._validate_value("daily_consumption", consumption)
        if intake is not None:
            intake = self._validate_value("daily_intake", intake)
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
        amount = self._validate_value("amount", amount, positive=True)
        r = self.db.get_resource(rtype)
        if r is None:
            return
        r.current_amount = max(0, r.current_amount - amount)
        r.estimated_remaining_hours = self._estimate_remaining(r)
        self.db.upsert_resource(r)

    # Sentinel: -1 means "sustained / cannot estimate" (consumption=0 or intake>=consumption).
    # Display layer should render this as "--" or t("web_power_sustained").
    SUSTAINED = -1.0

    @classmethod
    def _validate_value(cls, field: str, value: float, *, positive: bool = False) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ResourceValidationError(field, "not_numeric") from exc
        if not math.isfinite(number):
            raise ResourceValidationError(field, "not_finite")
        if positive and number <= 0:
            raise ResourceValidationError(field, "not_positive")
        if not positive and number < 0:
            raise ResourceValidationError(field, "negative")
        if number > cls.MAX_RESOURCE_VALUE:
            raise ResourceValidationError(field, "too_large")
        return number

    def _estimate_remaining(self, r: Resource) -> float:
        if r.type == ResourceType.POWER:
            if r.daily_consumption <= r.daily_intake:
                return self.SUSTAINED
            net_hourly = (r.daily_consumption - r.daily_intake) / 24.0
            if net_hourly <= 0:
                return self.SUSTAINED
            return r.current_amount / net_hourly
        elif r.type in (ResourceType.WATER, ResourceType.FOOD):
            if r.daily_consumption <= 0:
                return self.SUSTAINED
            return (r.current_amount / r.daily_consumption) * 24.0
        elif r.type == ResourceType.FIRE:
            if r.daily_consumption <= 0:
                return self.SUSTAINED
            return (r.current_amount / r.daily_consumption) * 24.0
        return 0.0

    def get_operating_mode(self) -> OperatingMode:
        state = self.db.get_operating_state()
        return OperatingMode(state.mode)

    def determine_operating_mode(self) -> OperatingMode:
        power = self.db.get_resource(ResourceType.POWER)
        if power is None or not self.is_configured(power):
            return OperatingMode.STANDARD
        if not self.has_remaining_estimate(power):
            return OperatingMode.PROACTIVE
        hours = power.estimated_remaining_hours
        for mode in [OperatingMode.PROACTIVE, OperatingMode.STANDARD,
                      OperatingMode.ECONOMY, OperatingMode.HIBERNATION]:
            if hours >= POWER_MODE_THRESHOLDS[mode]:
                return mode
        return OperatingMode.HIBERNATION

    def update_operating_mode(self) -> tuple[OperatingMode, bool]:
        state = self.db.get_operating_state()
        if state.mode_manual_override:
            # Operator pinned the mode; do not auto-adapt.
            return OperatingMode(state.mode), False
        new_mode = self.determine_operating_mode()
        old_mode = OperatingMode(state.mode)
        changed = new_mode != old_mode
        if changed:
            state.mode = new_mode.value
            power = self.db.get_resource(ResourceType.POWER)
            state.power_remaining_hours = power.estimated_remaining_hours if power else 0
            state.last_mode_change = datetime.now().isoformat()
            self.db.save_operating_state(state)
        return new_mode, changed

    def check_warnings(self) -> list[dict]:
        warnings = []
        power = self.db.get_resource(ResourceType.POWER)
        if power and self.has_remaining_estimate(power):
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
        if water and self.has_remaining_estimate(water):
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
        if food and self.has_remaining_estimate(food):
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
        if fire and self.is_configured(fire):
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
        if storage and self.is_configured(storage):
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
                t("advice_economy_1"),
                t("advice_economy_2"),
                t("advice_economy_3"),
                t("advice_economy_4"),
                t("advice_economy_5"),
            ]
        elif mode == OperatingMode.HIBERNATION:
            advice = [
                t("advice_hibernation_1"),
                t("advice_hibernation_2"),
                t("advice_hibernation_3"),
                t("advice_hibernation_4"),
            ]
        elif mode == OperatingMode.STANDARD:
            advice = [
                t("advice_standard_1"),
                t("advice_standard_2"),
                t("advice_standard_3"),
            ]
        return advice

    def get_resource_summary(self) -> str:
        resources = self.get_all_resources()
        state = self.db.get_operating_state()
        mode = OperatingMode(state.mode)
        mode_names = {
            OperatingMode.PROACTIVE: t("mode_proactive"),
            OperatingMode.STANDARD: t("mode_standard"),
            OperatingMode.ECONOMY: t("mode_economy"),
            OperatingMode.HIBERNATION: t("mode_hibernation"),
            OperatingMode.RECOVERY: t("mode_recovery"),
        }
        lines = [
            t("operating_mode_label", mode=mode_names.get(mode, mode.value)),
            "",
        ]

        has_data = False
        for r in resources:
            is_offline = r.current_amount == 0 and r.daily_consumption == 0
            if is_offline:
                icon = {
                    ResourceType.POWER: "⚡", ResourceType.WATER: "💧",
                    ResourceType.FOOD: "🍞", ResourceType.FIRE: "🔥",
                    ResourceType.STORAGE: "💾",
                }.get(r.type, "📦")
                label = t(f"resource_{r.type.value}")
                lines.append(f"  {icon} {label}: [dim]{t('resource_offline')}[/]")
                continue

            has_data = True
            if r.type == ResourceType.POWER:
                lines.append(t("res_power_fmt", amount=r.current_amount, hours=r.estimated_remaining_hours, consumption=r.daily_consumption, intake=r.daily_intake))
            elif r.type == ResourceType.WATER:
                days = r.estimated_remaining_hours / 24.0
                lines.append(t("res_water_fmt", amount=r.current_amount, days=days, consumption=r.daily_consumption))
            elif r.type == ResourceType.FOOD:
                days = r.estimated_remaining_hours / 24.0
                lines.append(t("res_food_fmt", amount=r.current_amount, days=days, consumption=r.daily_consumption))
            elif r.type == ResourceType.FIRE:
                lines.append(t("res_fire_fmt", amount=r.current_amount, consumption=r.daily_consumption))
            elif r.type == ResourceType.STORAGE:
                total = r.daily_consumption
                used = r.daily_intake
                pct = ((total - used) / total * 100) if total > 0 else 0
                lines.append(t("res_storage_fmt", used=used, total=total, pct=pct))

        if not has_data:
            lines.append(t("resource_not_configured"))
            lines.append(t("resource_set_hint"))
            lines.append(t("resource_types_hint"))
        else:
            lines.append("\n" + t("data_disclaimer"))

        return "\n".join(lines)


_DEFAULT_RESOURCES = {
    ResourceType.POWER: Resource(
        type=ResourceType.POWER,
        current_amount=0.0,
        unit="Wh",
        daily_consumption=0.0,
        daily_intake=0.0,
        estimated_remaining_hours=0.0,
        last_updated=""
    ),
    ResourceType.WATER: Resource(
        type=ResourceType.WATER,
        current_amount=0.0,
        unit="L",
        daily_consumption=0.0,
        daily_intake=0.0,
        estimated_remaining_hours=0.0,
        last_updated=""
    ),
    ResourceType.FOOD: Resource(
        type=ResourceType.FOOD,
        current_amount=0.0,
        unit="kcal",
        daily_consumption=0.0,
        daily_intake=0.0,
        estimated_remaining_hours=0.0,
        last_updated=""
    ),
    ResourceType.FIRE: Resource(
        type=ResourceType.FIRE,
        current_amount=0.0,
        unit="uses",
        daily_consumption=0.0,
        daily_intake=0.0,
        estimated_remaining_hours=0.0,
        last_updated=""
    ),
    ResourceType.STORAGE: Resource(
        type=ResourceType.STORAGE,
        current_amount=0.0,
        unit="GB",
        daily_consumption=0.0,
        daily_intake=0.0,
        estimated_remaining_hours=0.0,
        last_updated=""
    ),
}
