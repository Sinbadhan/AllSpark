"""Confirmed conversation-to-state action loop for SHA-242."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from allspark.core.i18n import mark, render, t
from allspark.core.models import RESOURCE_UNITS, ResourceType

_CONVERSATION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_NUMBER = (
    r"(?:\d+(?:\.\d+)?|[一二两三四五六七八九十]+|"
    r"one|two|three|four|five|six|seven|eight|nine|ten)"
)
_CONFIRM = {"confirm", "confirmed", "yes", "y", "确认", "确定", "是"}
_CANCEL = {"cancel", "no", "n", "取消", "不", "否", "不要"}
_RESOURCE_ALIASES = {
    ResourceType.WATER: ("饮用水", "水", "water"),
    ResourceType.FOOD: ("食物", "食品", "food", "kcal", "千卡"),
    ResourceType.POWER: ("电力", "电量", "power", "battery", "wh", "kwh"),
    ResourceType.FIRE: ("火源", "燃料", "fire", "fuel"),
    ResourceType.STORAGE: ("存储", "储存空间", "storage", "disk", "gb"),
}
_FACT_CUES = ("有", "剩", "库存", "储备", "have", "left", "remaining", "stock")


@dataclass
class InteractionResult:
    response: str
    metadata: dict[str, Any]


@dataclass
class ResourceDraft:
    resource_type: ResourceType
    duration_days: float | None = None
    amount: float | None = None
    people_count: int | None = None
    daily_consumption: float | None = None
    daily_intake: float | None = None
    capacity: float | None = None
    updated_at: float = 0.0


class ActionLoopService:
    """Collect resource context, require confirmation, then reassess."""

    MAX_STATES = 128
    STATE_TTL_SECONDS = 10 * 60

    def __init__(
        self,
        db,
        resource_manager,
        survival_plan,
        mission_planner,
        *,
        timeline_provider: Callable[[], Any] | None = None,
    ):
        self.db = db
        self.resource_manager = resource_manager
        self.survival_plan = survival_plan
        self.mission_planner = mission_planner
        self.timeline_provider = timeline_provider or (lambda: None)
        self._pending: dict[str, ResourceDraft] = {}

    def process_chat(
        self,
        message: str,
        *,
        conversation_id: str | None,
    ) -> InteractionResult | None:
        if not isinstance(message, str):
            return None
        conversation = self._valid_conversation(conversation_id)
        if conversation is None:
            return None
        self._expire_states()
        normalized = message.strip().lower()
        pending = self._pending.get(conversation)

        if pending is not None and normalized in _CANCEL:
            del self._pending[conversation]
            return self._result(
                "action_loop_cancelled",
                pending.resource_type,
                status="cancelled",
            )
        if pending is not None and normalized in _CONFIRM:
            return self._apply(conversation, pending)

        parsed = self._parse(message, pending=pending)
        if parsed is None:
            return None
        parsed.updated_at = time.monotonic()
        self._pending[conversation] = parsed
        self._trim_states()

        missing = self._missing_context(parsed)
        if missing:
            return self._result(
                "action_loop_context_required",
                parsed.resource_type,
                status="needs_context",
                fields=t(
                    "action_loop_context_fields_" + "_".join(missing),
                    unit=RESOURCE_UNITS[parsed.resource_type],
                ),
            )
        return self._confirmation(parsed)

    def create_task_from_knowledge(self, knowledge_id: str):
        entry = self.db.get_knowledge(knowledge_id)
        if entry is None:
            return None
        assessment = self.survival_plan.generate_current()
        phase = assessment.phase
        description_parts = [entry.summary]
        if entry.steps:
            description_parts.append("\n".join(entry.steps[:3]))
        return self.mission_planner.create_task(
            title=entry.title,
            description="\n\n".join(part for part in description_parts if part),
            phase=phase,
            priority=max(0, min(30, entry.priority * 10)),
            source="knowledge",
            source_ref=entry.id,
        )

    @staticmethod
    def task_payload(task) -> dict[str, Any]:
        return {
            "id": task.id,
            "phase": task.phase if task.phase >= 0 else None,
            "phase_status": "known" if task.phase >= 0 else "unknown",
            "priority": task.priority,
            "title": render(task.title),
            "description": render(task.description),
            "status": task.status,
            "task_type": task.task_type,
            "source": task.source,
            "source_ref": task.source_ref,
            "result": task.result,
            "evidence": task.evidence,
            "completed_at": task.completed_at,
        }

    def _apply(
        self,
        conversation: str,
        draft: ResourceDraft,
    ) -> InteractionResult:
        missing = self._missing_context(draft)
        if missing:
            return self._result(
                "action_loop_context_required",
                draft.resource_type,
                status="needs_context",
                fields=t(
                    "action_loop_context_fields_" + "_".join(missing),
                    unit=RESOURCE_UNITS[draft.resource_type],
                ),
            )

        assert draft.amount is not None
        current = self.db.get_resource(draft.resource_type)
        consumption = draft.daily_consumption
        intake = draft.daily_intake
        rates_known = consumption is not None and intake is not None
        people = draft.people_count
        if people is None and current and current.people_count_known:
            people = current.people_count
        people_known = people is not None
        capacity_known = draft.capacity is not None

        old_plan = self.db.get_survival_plan(active_only=True)
        self.resource_manager.update_resource(
            draft.resource_type,
            draft.amount,
            consumption=consumption,
            intake=intake,
            rate_basis="group_total" if rates_known else "unknown",
            source="user_input",
            people_count=people or 1,
            people_count_known=people_known,
            as_of=datetime.now(timezone.utc).isoformat(),
            amount_known=True,
            consumption_known=rates_known,
            intake_known=rates_known,
            capacity=draft.capacity,
            capacity_known=capacity_known,
            confirm_outlier=True,
        )
        if people_known:
            self.db.save_survivor_state("people_count", str(people))
            self.db.save_survivor_state("people_count_status", "known")

        plan = self.survival_plan.generate_current()
        primary_ids = self.survival_plan.primary_candidate_ids(plan)
        if not primary_ids:
            raise RuntimeError("reassessment produced no primary action")
        accepted_action_id = primary_ids[0]
        self.db.replace_active_survival_plan(
            plan,
            accepted_action_id=accepted_action_id,
        )
        timeline = self.timeline_provider()
        if timeline is not None:
            timeline.record_resource_change(
                draft.resource_type.value,
                mark(
                    "action_loop_timeline_resource_update",
                    resource=draft.resource_type.value,
                    amount=draft.amount,
                    unit=RESOURCE_UNITS[draft.resource_type],
                ),
            )
        self._pending.pop(conversation, None)
        plan_payload = self.survival_plan.payload(plan)
        action = next(
            item
            for item in plan_payload["actions"]
            if item["id"] == accepted_action_id
        )
        plan_changed = old_plan is None or old_plan.fingerprint != plan.fingerprint
        response = t(
            "action_loop_applied",
            resource=t(f"resource_{draft.resource_type.value}"),
            amount=draft.amount,
            unit=RESOURCE_UNITS[draft.resource_type],
            action=action["title"],
        )
        return InteractionResult(
            response=response,
            metadata={
                "kind": "resource_update",
                "status": "applied",
                "resource": draft.resource_type.value,
                "state_changed": True,
                "plan_changed": plan_changed,
                "plan_id": plan.id,
                "primary_action_id": accepted_action_id,
            },
        )

    def _confirmation(self, draft: ResourceDraft) -> InteractionResult:
        assert draft.amount is not None
        consumption = (
            t(
                "action_loop_rate_known",
                consumption=draft.daily_consumption,
                intake=draft.daily_intake,
                unit=RESOURCE_UNITS[draft.resource_type],
            )
            if draft.daily_consumption is not None and draft.daily_intake is not None
            else t("action_loop_rate_unknown")
        )
        people = (
            str(draft.people_count)
            if draft.people_count is not None
            else t("action_loop_not_applicable")
        )
        return self._result(
            "action_loop_confirm",
            draft.resource_type,
            status="needs_confirmation",
            amount=draft.amount,
            unit=RESOURCE_UNITS[draft.resource_type],
            people=people,
            rate=consumption,
            capacity=(
                t(
                    "action_loop_capacity_known",
                    amount=draft.capacity,
                    unit=RESOURCE_UNITS[draft.resource_type],
                )
                if draft.capacity is not None
                else t("action_loop_capacity_not_applicable")
            ),
        )

    def _result(
        self,
        key: str,
        resource_type: ResourceType,
        *,
        status: str,
        **kwargs: Any,
    ) -> InteractionResult:
        return InteractionResult(
            response=t(
                key,
                resource=t(f"resource_{resource_type.value}"),
                **kwargs,
            ),
            metadata={
                "kind": "resource_update",
                "status": status,
                "resource": resource_type.value,
                "state_changed": False,
            },
        )

    def _parse(
        self,
        message: str,
        *,
        pending: ResourceDraft | None,
    ) -> ResourceDraft | None:
        lowered = message.lower()
        resource_type = pending.resource_type if pending else self._resource_type(lowered)
        if resource_type is None:
            return None
        duration = self._duration_days(lowered)
        amount = self._amount(lowered, resource_type)
        people = self._people(lowered)
        daily = self._daily_consumption(lowered, resource_type)
        capacity = self._capacity(lowered, resource_type)
        if pending is None and not (
            any(cue in lowered for cue in _FACT_CUES)
            and (duration is not None or amount is not None)
        ):
            return None
        draft = ResourceDraft(
            resource_type=resource_type,
            duration_days=duration if duration is not None else getattr(pending, "duration_days", None),
            amount=amount if amount is not None else getattr(pending, "amount", None),
            people_count=people if people is not None else getattr(pending, "people_count", None),
            daily_consumption=daily if daily is not None else getattr(pending, "daily_consumption", None),
            daily_intake=getattr(pending, "daily_intake", None),
            capacity=capacity if capacity is not None else getattr(pending, "capacity", None),
        )
        if (
            draft.daily_consumption is None
            and draft.amount is not None
            and draft.duration_days is not None
            and draft.duration_days > 0
        ):
            draft.daily_consumption = draft.amount / draft.duration_days
            draft.daily_intake = 0.0
        current = self.db.get_resource(resource_type)
        if current is not None:
            if draft.daily_consumption is None and current.consumption_known:
                draft.daily_consumption = current.daily_consumption
            if draft.daily_intake is None and current.intake_known:
                draft.daily_intake = current.daily_intake
            if (
                resource_type == ResourceType.STORAGE
                and draft.capacity is None
                and current.capacity_known
            ):
                draft.capacity = current.capacity
        if daily is not None and draft.daily_intake is None:
            draft.daily_intake = 0.0
        return draft

    @staticmethod
    def _resource_type(text: str) -> ResourceType | None:
        for resource_type, aliases in _RESOURCE_ALIASES.items():
            if any(alias in text for alias in aliases):
                return resource_type
        return None

    @classmethod
    def _duration_days(cls, text: str) -> float | None:
        match = re.search(
            rf"({_NUMBER})\s*(天|日|days?|小时|hours?|hrs?)",
            text,
            re.IGNORECASE,
        )
        if not match:
            return None
        value = cls._number(match.group(1))
        return value / 24 if match.group(2).lower() in {"小时", "hour", "hours", "hr", "hrs"} else value

    @classmethod
    def _amount(cls, text: str, resource_type: ResourceType) -> float | None:
        units = {
            ResourceType.WATER: r"升|公升|l(?:iters?)?",
            ResourceType.FOOD: r"千卡|大卡|kcal",
            ResourceType.POWER: r"kwh|wh|瓦时",
            ResourceType.FIRE: r"次|uses?",
            ResourceType.STORAGE: r"gb|吉字节",
        }[resource_type]
        matches = list(re.finditer(rf"({_NUMBER})\s*({units})", text, re.IGNORECASE))
        for match in matches:
            if resource_type == ResourceType.STORAGE:
                prefix = text[max(0, match.start() - 14):match.start()]
                if re.search(r"(?:容量|总容量|capacity|total)\s*(?:是|为|:)?\s*$", prefix):
                    continue
            tail = text[match.end(): match.end() + 8]
            if re.match(r"\s*(?:/|每)\s*(?:天|日|day)", tail, re.IGNORECASE):
                continue
            value = cls._number(match.group(1))
            if resource_type == ResourceType.POWER and match.group(2).lower() == "kwh":
                value *= 1000
            return value
        return None

    @classmethod
    def _daily_consumption(
        cls, text: str, resource_type: ResourceType
    ) -> float | None:
        units = {
            ResourceType.WATER: r"升|公升|l(?:iters?)?",
            ResourceType.FOOD: r"千卡|大卡|kcal",
            ResourceType.POWER: r"kwh|wh|瓦时",
            ResourceType.FIRE: r"次|uses?",
            ResourceType.STORAGE: r"gb|吉字节",
        }[resource_type]
        match = re.search(
            rf"(?:每天|每日|per\s+day|daily)\s*({_NUMBER})\s*({units})"
            rf"|({_NUMBER})\s*({units})\s*(?:/|每)\s*(?:天|日|day)",
            text,
            re.IGNORECASE,
        )
        if not match:
            return None
        raw_value = match.group(1) or match.group(3)
        raw_unit = match.group(2) or match.group(4)
        value = cls._number(raw_value)
        if resource_type == ResourceType.POWER and raw_unit.lower() == "kwh":
            value *= 1000
        return value

    @classmethod
    def _capacity(cls, text: str, resource_type: ResourceType) -> float | None:
        if resource_type != ResourceType.STORAGE:
            return None
        match = re.search(
            rf"(?:容量|总容量|capacity|total)\s*(?:是|为|:)?\s*({_NUMBER})\s*(gb|吉字节)"
            rf"|({_NUMBER})\s*(gb|吉字节)\s*(?:容量|capacity)",
            text,
            re.IGNORECASE,
        )
        if not match:
            return None
        return cls._number(match.group(1) or match.group(3))

    @classmethod
    def _people(cls, text: str) -> int | None:
        match = re.search(rf"({_NUMBER})\s*(?:个人|人|people|persons?)", text, re.IGNORECASE)
        if not match:
            return None
        value = cls._number(match.group(1))
        return int(value) if value.is_integer() and value > 0 else None

    @staticmethod
    def _number(value: str) -> float:
        try:
            return float(value)
        except ValueError:
            pass
        english = {
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
        }
        if value.lower() in english:
            return float(english[value.lower()])
        digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
        if value == "十":
            return 10.0
        if "十" in value:
            left, _, right = value.partition("十")
            tens = digits.get(left, 1) if left else 1
            ones = digits.get(right, 0) if right else 0
            return float(tens * 10 + ones)
        return float(digits[value])

    def _missing_context(self, draft: ResourceDraft) -> list[str]:
        missing = []
        if draft.amount is None:
            missing.append("amount")
        if (
            draft.resource_type in {ResourceType.WATER, ResourceType.FOOD}
            and draft.people_count is None
        ):
            missing.append("people")
        if (
            draft.resource_type == ResourceType.STORAGE
            and draft.amount is not None
            and draft.capacity is not None
            and draft.amount > draft.capacity
        ):
            missing.append("capacity")
        return missing

    @staticmethod
    def _valid_conversation(value: str | None) -> str | None:
        return value if isinstance(value, str) and _CONVERSATION_ID.fullmatch(value) else None

    def _expire_states(self) -> None:
        cutoff = time.monotonic() - self.STATE_TTL_SECONDS
        self._pending = {
            key: value
            for key, value in self._pending.items()
            if value.updated_at >= cutoff
        }

    def _trim_states(self) -> None:
        if len(self._pending) <= self.MAX_STATES:
            return
        oldest = sorted(self._pending, key=lambda key: self._pending[key].updated_at)
        for key in oldest[: len(self._pending) - self.MAX_STATES]:
            self._pending.pop(key, None)
