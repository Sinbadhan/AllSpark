import logging
import math
from datetime import datetime, timedelta
from typing import Any, Optional

from allspark.core.config import POWER_MODE_THRESHOLDS, RESOURCE_WARNING_THRESHOLDS
from allspark.core.database import Database
from allspark.core.i18n import t
from allspark.core.models import RESOURCE_UNITS, OperatingMode, Resource, ResourceType

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
    RESOURCE_SOFT_MAX = {
        ResourceType.POWER: 1_000_000.0,
        ResourceType.WATER: 100_000.0,
        ResourceType.FOOD: 100_000_000.0,
        ResourceType.FIRE: 100_000.0,
        ResourceType.STORAGE: 100_000.0,
    }
    ALLOWED_SOURCES = {
        "user_input",
        "sensor",
        "estimate",
        "migration",
        "system",
        "mixed",
    }

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
        return r.amount_known

    def has_remaining_estimate(self, r: Resource) -> bool:
        return self.remaining_status(r) == "finite"

    def remaining_status(self, r: Resource) -> str:
        """Return the public remaining-time state without leaking sentinels."""
        if not self.has_complete_rate_data(r):
            return "unknown"
        if r.daily_consumption <= r.daily_intake:
            return "sustained"
        return "finite"

    def has_complete_rate_data(self, r: Resource) -> bool:
        return (
            r.amount_known
            and r.consumption_known
            and r.intake_known
            and r.rate_basis == "group_total"
        )

    def update_resource(self, rtype: ResourceType, amount: Optional[float],
                        consumption: Optional[float] = None,
                        intake: Optional[float] = None,
                        *, source: str = "user_input",
                        rate_basis: str = "group_total",
                        people_count: int = 1,
                        people_count_known: bool = True,
                        as_of: Optional[str] = None,
                        amount_known: Optional[bool] = None,
                        consumption_known: Optional[bool] = None,
                        intake_known: Optional[bool] = None,
                        capacity: Optional[float] = None,
                        capacity_known: Optional[bool] = None,
                        confirm_outlier: bool = False):
        for field, known in (
            ("amount_known", amount_known),
            ("consumption_known", consumption_known),
            ("intake_known", intake_known),
            ("capacity_known", capacity_known),
            ("people_count_known", people_count_known),
        ):
            if known is not None and not isinstance(known, bool):
                raise ResourceValidationError(field, "not_boolean")
        amount_known = amount is not None if amount_known is None else amount_known
        consumption_known = (
            consumption is not None if consumption_known is None else consumption_known
        )
        intake_known = intake is not None if intake_known is None else intake_known
        capacity_known = capacity is not None if capacity_known is None else capacity_known
        if amount_known and amount is None:
            raise ResourceValidationError("amount", "required")
        if consumption_known and consumption is None:
            raise ResourceValidationError("daily_consumption", "required")
        if intake_known and intake is None:
            raise ResourceValidationError("daily_intake", "required")
        if capacity_known and capacity is None:
            raise ResourceValidationError("capacity", "required")
        if capacity_known and rtype != ResourceType.STORAGE:
            raise ResourceValidationError("capacity", "capacity_storage_only")
        if consumption_known or intake_known:
            if rate_basis != "group_total":
                raise ResourceValidationError("rate_basis", "invalid_rate_basis")
        else:
            rate_basis = "unknown"
        if not isinstance(confirm_outlier, bool):
            raise ResourceValidationError("confirm_outlier", "not_boolean")
        amount_value = self._validate_value("amount", amount) if amount_known else 0.0
        consumption_value = 0.0
        intake_value = 0.0
        capacity_value = 0.0
        if consumption_known:
            consumption = self._validate_value("daily_consumption", consumption)
            consumption_value = consumption
        if intake_known:
            intake = self._validate_value("daily_intake", intake)
            intake_value = intake
        if capacity_known:
            capacity_value = self._validate_value("capacity", capacity)
        if capacity_known and amount_known and capacity_value < amount_value:
            raise ResourceValidationError("capacity", "capacity_below_remaining")
        soft_max = self.RESOURCE_SOFT_MAX[rtype]
        for field, value, known in (
            ("amount", amount_value, amount_known),
            ("daily_consumption", consumption_value, consumption_known),
            ("daily_intake", intake_value, intake_known),
            ("capacity", capacity_value, capacity_known),
        ):
            if known and value > soft_max and not confirm_outlier:
                raise ResourceValidationError(field, "outlier_confirmation")
        if not isinstance(source, str) or source not in self.ALLOWED_SOURCES:
            raise ResourceValidationError("source", "invalid_source")
        people_count = self._validate_people_count(people_count)
        snapshot_time = self._validate_as_of(as_of)
        r = self.db.get_resource(rtype)
        if r is None:
            return
        r.current_amount = amount_value
        r.daily_consumption = consumption_value
        r.daily_intake = intake_value
        r.rate_basis = rate_basis
        r.unit = RESOURCE_UNITS[rtype]
        r.amount_known = amount_known
        r.consumption_known = consumption_known
        r.intake_known = intake_known
        r.capacity = capacity_value
        r.capacity_known = capacity_known
        r.source = source
        r.people_count = people_count
        r.people_count_known = people_count_known
        r.as_of = snapshot_time
        r.estimated_remaining_hours = self._estimate_remaining(r)
        self.db.upsert_resource(r)

    def merge_resource_observation(
        self,
        rtype: ResourceType,
        *,
        amount: Optional[float] = None,
        consumption: Optional[float] = None,
        intake: Optional[float] = None,
        source: str,
        as_of: Optional[str] = None,
    ) -> None:
        """Merge a controlled partial observation without erasing known fields."""
        current = self.db.get_resource(rtype)
        if current is None:
            return
        if not isinstance(source, str) or source not in self.ALLOWED_SOURCES:
            raise ResourceValidationError("source", "invalid_source")
        incoming_as_of = self._validate_as_of(as_of)
        retained_known_field = any(
            (
                amount is None and current.amount_known,
                consumption is None and current.consumption_known,
                intake is None and current.intake_known,
                current.capacity_known,
            )
        )
        merged_source, merged_as_of = self._partial_snapshot_metadata(
            current,
            source=source,
            incoming_as_of=incoming_as_of,
            retained_known_field=retained_known_field,
        )
        self.update_resource(
            rtype,
            current.current_amount if amount is None else amount,
            consumption=(
                current.daily_consumption if consumption is None else consumption
            ),
            intake=current.daily_intake if intake is None else intake,
            rate_basis=current.rate_basis if current.rate_basis != "unknown" else "group_total",
            source=merged_source,
            people_count=current.people_count,
            people_count_known=current.people_count_known,
            as_of=merged_as_of,
            amount_known=current.amount_known if amount is None else True,
            consumption_known=(
                current.consumption_known if consumption is None else True
            ),
            intake_known=current.intake_known if intake is None else True,
            capacity=current.capacity if current.capacity_known else None,
            capacity_known=current.capacity_known,
        )

    def mark_unknown(
        self,
        rtype: ResourceType,
        *,
        source: str = "user_input",
        people_count: int = 1,
        people_count_known: bool = True,
        as_of: Optional[str] = None,
    ) -> None:
        """Persist an explicit unknown; unknown is never represented as zero."""
        self.update_resource(
            rtype,
            None,
            source=source,
            people_count=people_count,
            people_count_known=people_count_known,
            as_of=as_of,
            amount_known=False,
            consumption_known=False,
            intake_known=False,
            capacity_known=False,
        )

    def consume_resource(
        self,
        rtype: ResourceType,
        amount: float,
        *,
        source: str = "user_input",
        as_of: Optional[str] = None,
    ):
        amount = self._validate_value("amount", amount, positive=True)
        r = self.db.get_resource(rtype)
        if r is None:
            return
        if not r.amount_known:
            raise ResourceValidationError("amount", "unknown_inventory")
        if not isinstance(source, str) or source not in self.ALLOWED_SOURCES:
            raise ResourceValidationError("source", "invalid_source")
        incoming_as_of = self._validate_as_of(as_of)
        retained_known_field = any(
            (r.consumption_known, r.intake_known, r.capacity_known)
        )
        merged_source, merged_as_of = self._partial_snapshot_metadata(
            r,
            source=source,
            incoming_as_of=incoming_as_of,
            retained_known_field=retained_known_field,
        )
        r.current_amount = max(0, r.current_amount - amount)
        r.source = merged_source
        r.as_of = merged_as_of
        r.estimated_remaining_hours = self._estimate_remaining(r)
        self.db.upsert_resource(r)

    # Sentinel: -1 means "sustained / cannot estimate" (consumption=0 or intake>=consumption).
    # Display layer should render this as "--" or t("web_power_sustained").
    SUSTAINED = -1.0

    @classmethod
    def _validate_value(cls, field: str, value: Any, *, positive: bool = False) -> float:
        if isinstance(value, bool):
            raise ResourceValidationError(field, "not_numeric")
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

    @classmethod
    def validate_value(cls, field: str, value: Any, *, positive: bool = False) -> float:
        """Validate a resource number for controlled service entry points."""
        return cls._validate_value(field, value, positive=positive)

    @staticmethod
    def _validate_people_count(value: Any) -> int:
        if isinstance(value, bool):
            raise ResourceValidationError("people_count", "not_integer")
        if isinstance(value, int):
            people_count = value
        elif isinstance(value, str) and value.isdigit():
            people_count = int(value)
        else:
            raise ResourceValidationError("people_count", "not_integer")
        if not 1 <= people_count <= 10_000:
            raise ResourceValidationError("people_count", "people_range")
        return people_count

    @staticmethod
    def validate_people_count(value: Any) -> int:
        """Validate a group size without silently coercing ambiguous input."""
        return ResourceManager._validate_people_count(value)

    @staticmethod
    def _validate_as_of(value: Any) -> str:
        if value is None:
            return datetime.now().isoformat()
        if not isinstance(value, str) or not value.strip():
            raise ResourceValidationError("as_of", "invalid_timestamp")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ResourceValidationError("as_of", "invalid_timestamp") from exc
        now = datetime.now(parsed.tzinfo) if parsed.tzinfo else datetime.now()
        if parsed > now + timedelta(minutes=5):
            raise ResourceValidationError("as_of", "future_timestamp")
        return value

    @staticmethod
    def validate_as_of(value: Any) -> str:
        """Validate or create one honest snapshot timestamp for shared inputs."""
        return ResourceManager._validate_as_of(value)

    @staticmethod
    def _oldest_valid_timestamp(first: str, second: str) -> str:
        def timestamp(value: str) -> float | None:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except (AttributeError, OverflowError, TypeError, ValueError):
                return None

        first_value = timestamp(first)
        second_value = timestamp(second)
        if first_value is None:
            return second
        if second_value is None:
            return first
        return first if first_value <= second_value else second

    def _partial_snapshot_metadata(
        self,
        current: Resource,
        *,
        source: str,
        incoming_as_of: str,
        retained_known_field: bool,
    ) -> tuple[str, str]:
        if not retained_known_field:
            return source, incoming_as_of
        return (
            "mixed",
            self._oldest_valid_timestamp(
                current.as_of or current.last_updated,
                incoming_as_of,
            ),
        )

    def _estimate_remaining(self, r: Resource) -> float:
        return self.estimate_remaining(r)

    def estimate_remaining(self, r: Resource) -> float:
        if not self.has_complete_rate_data(r):
            return 0.0
        if r.type == ResourceType.POWER:
            if r.daily_consumption <= r.daily_intake:
                return self.SUSTAINED
            net_hourly = (r.daily_consumption - r.daily_intake) / 24.0
            if net_hourly <= 0:
                return self.SUSTAINED
            return r.current_amount / net_hourly
        elif r.type in (ResourceType.WATER, ResourceType.FOOD, ResourceType.FIRE):
            net_daily = r.daily_consumption - r.daily_intake
            if net_daily <= 0:
                return self.SUSTAINED
            return (r.current_amount / net_daily) * 24.0
        elif r.type == ResourceType.STORAGE:
            net_daily = r.daily_consumption - r.daily_intake
            if net_daily <= 0:
                return self.SUSTAINED
            return (r.current_amount / net_daily) * 24.0
        return 0.0

    def get_operating_mode(self) -> OperatingMode:
        state = self.db.get_operating_state()
        return OperatingMode(state.mode)

    def determine_operating_mode(self) -> OperatingMode:
        power = self.db.get_resource(ResourceType.POWER)
        if power is None or not self.is_configured(power):
            return OperatingMode.STANDARD
        if not self.has_complete_rate_data(power):
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
        if storage and self.is_configured(storage) and storage.capacity_known:
            if storage.capacity > 0:
                pct = (storage.current_amount / storage.capacity) * 100
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
            is_offline = not r.amount_known
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
            if not self.has_complete_rate_data(r):
                lines.append(
                    t(
                        "resource_amount_known_rate_unknown",
                        label=t(f"resource_{r.type.value}"),
                        amount=r.current_amount,
                        unit=r.unit,
                    )
                )
                continue
            if self.remaining_status(r) == "sustained":
                lines.append(
                    f"  {t(f'resource_{r.type.value}')}: "
                    f"{r.current_amount:.1f}{r.unit} | {t('res_sustained')}"
                )
                continue
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
                total = r.capacity if r.capacity_known else 0
                pct = (r.current_amount / total * 100) if total > 0 else 0
                lines.append(
                    t(
                        "res_storage_fmt",
                        remaining=r.current_amount,
                        total=total,
                        pct=pct,
                    )
                )

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
        last_updated="",
        amount_known=False, consumption_known=False, intake_known=False,
        source="system",
    ),
    ResourceType.WATER: Resource(
        type=ResourceType.WATER,
        current_amount=0.0,
        unit="L",
        daily_consumption=0.0,
        daily_intake=0.0,
        estimated_remaining_hours=0.0,
        last_updated="",
        amount_known=False, consumption_known=False, intake_known=False,
        source="system",
    ),
    ResourceType.FOOD: Resource(
        type=ResourceType.FOOD,
        current_amount=0.0,
        unit="kcal",
        daily_consumption=0.0,
        daily_intake=0.0,
        estimated_remaining_hours=0.0,
        last_updated="",
        amount_known=False, consumption_known=False, intake_known=False,
        source="system",
    ),
    ResourceType.FIRE: Resource(
        type=ResourceType.FIRE,
        current_amount=0.0,
        unit="uses",
        daily_consumption=0.0,
        daily_intake=0.0,
        estimated_remaining_hours=0.0,
        last_updated="",
        amount_known=False, consumption_known=False, intake_known=False,
        source="system",
    ),
    ResourceType.STORAGE: Resource(
        type=ResourceType.STORAGE,
        current_amount=0.0,
        unit="GB",
        daily_consumption=0.0,
        daily_intake=0.0,
        estimated_remaining_hours=0.0,
        last_updated="",
        amount_known=False, consumption_known=False, intake_known=False,
        source="system",
    ),
}
