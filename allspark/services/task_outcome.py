"""Traceable task outcomes and deterministic reassessment (SHA-243)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from allspark.core.database import Database
from allspark.core.i18n import mark
from allspark.core.models import ResourceType, TaskStatus
from allspark.services.resource_manager import ResourceManager, ResourceValidationError

logger = logging.getLogger(__name__)


class TaskOutcomeError(ValueError):
    def __init__(self, field: str, code: str, *, status_code: int = 422):
        self.field = field
        self.code = code
        self.status_code = status_code
        super().__init__(f"{field}: {code}")


class TaskOutcomeService:
    TERMINAL = {
        TaskStatus.COMPLETED.value,
        TaskStatus.FAILED.value,
        TaskStatus.SKIPPED.value,
    }

    def __init__(
        self,
        db: Database,
        resource_manager: ResourceManager,
        survival_plan,
        mission_planner,
        *,
        timeline_provider: Callable[[], Any | None],
        rule_engine_provider: Callable[[], Any | None],
    ):
        self.db = db
        self.resource_manager = resource_manager
        self.survival_plan = survival_plan
        self.mission_planner = mission_planner
        self.timeline_provider = timeline_provider
        self.rule_engine_provider = rule_engine_provider

    def record(
        self,
        task_id: str,
        *,
        status: str,
        result: Any,
        evidence: Any = None,
        resource_update: Any = None,
        confirm_resource_update: Any = False,
    ) -> dict[str, Any]:
        task = self.db.get_task(task_id)
        if task is None:
            raise TaskOutcomeError("task_id", "not_found", status_code=404)
        if task.status not in {TaskStatus.PENDING.value, TaskStatus.IN_PROGRESS.value}:
            raise TaskOutcomeError("status", "already_terminal", status_code=409)
        if status not in self.TERMINAL:
            raise TaskOutcomeError("status", "invalid_choice")

        normalized_result = self._text(result, "result", limit=2000)
        normalized_evidence = self._evidence(evidence)
        persisted_evidence = normalized_evidence
        if task.source == "survival_plan":
            persisted_evidence = list(
                dict.fromkeys([*task.evidence, *normalized_evidence])
            )
        normalized_update = self._resource_update(resource_update)
        if (
            status == TaskStatus.COMPLETED.value
            and task.source == "survival_plan"
            and not normalized_evidence
        ):
            raise TaskOutcomeError("evidence", "required")
        expected_resource = self._expected_resource_update(task.source_ref)
        if status == TaskStatus.COMPLETED.value and expected_resource:
            if normalized_update is None:
                raise TaskOutcomeError("resource_update", "required")
            if normalized_update["type"] != expected_resource:
                raise TaskOutcomeError("resource_update.type", "task_mismatch")
        if normalized_update is not None and confirm_resource_update is not True:
            raise TaskOutcomeError(
                "confirm_resource_update",
                "confirmation_required",
                status_code=409,
            )

        old_plan = self.db.get_survival_plan(active_only=True)
        with self.db.conn:
            if normalized_update is not None:
                try:
                    self.resource_manager.merge_resource_observation(
                        normalized_update["type"],
                        amount=normalized_update["amount"],
                        consumption=normalized_update.get("consumption"),
                        intake=normalized_update.get("intake"),
                        source="user_input",
                        as_of=datetime.now(timezone.utc).isoformat(),
                        commit=False,
                    )
                except ResourceValidationError as exc:
                    raise TaskOutcomeError(
                        f"resource_update.{exc.field}", exc.reason
                    ) from exc

            saved = self.db.record_task_outcome(
                task_id,
                status=status,
                result=normalized_result,
                evidence=persisted_evidence,
                commit=False,
            )
            if saved is None:
                raise TaskOutcomeError("status", "already_terminal", status_code=409)

            plan = self.survival_plan.generate_current()
            candidates = self.survival_plan.primary_candidate_ids(plan)
            if not candidates:
                raise RuntimeError("reassessment produced no primary action")
            self.db.replace_active_survival_plan(
                plan, accepted_action_id=candidates[0], commit=False
            )
            next_task = self.mission_planner.create_task_from_active_plan(
                self.survival_plan, commit=False
            )

        try:
            timeline = self.timeline_provider()
            if timeline is not None:
                timeline.record_system_event(
                    mark("timeline_task_outcome", title=task.title, status=status),
                    mark("timeline_task_outcome_desc", result=normalized_result),
                )
        except Exception:
            logger.exception("Task outcome saved, but timeline recording failed")
        rule_engine = self.rule_engine_provider()
        if rule_engine is not None and hasattr(
            rule_engine, "invalidate_assessment_cache"
        ):
            rule_engine.invalidate_assessment_cache()

        return {
            "task": saved,
            "plan": plan,
            "plan_changed": old_plan is None or old_plan.fingerprint != plan.fingerprint,
            "resource_changed": normalized_update is not None,
            "next_task": next_task[0] if next_task is not None else None,
        }

    @staticmethod
    def _text(value: Any, field: str, *, limit: int) -> str:
        if not isinstance(value, str) or not value.strip():
            raise TaskOutcomeError(field, "required")
        normalized = value.strip()
        if len(normalized) > limit:
            raise TaskOutcomeError(field, "too_long")
        return normalized

    @classmethod
    def _evidence(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list) or len(value) > 10:
            raise TaskOutcomeError("evidence", "invalid_list")
        return [cls._text(item, "evidence", limit=500) for item in value]

    def _resource_update(self, value: Any) -> dict[str, Any] | None:
        if value in (None, {}):
            return None
        if not isinstance(value, dict):
            raise TaskOutcomeError("resource_update", "invalid_object")
        try:
            resource_type = ResourceType(value.get("type"))
        except (TypeError, ValueError) as exc:
            raise TaskOutcomeError("resource_update.type", "invalid_choice") from exc
        try:
            amount = ResourceManager.validate_value(
                "amount", value.get("amount")
            )
        except ResourceValidationError as exc:
            raise TaskOutcomeError(
                f"resource_update.{exc.field}", exc.reason
            ) from exc
        current = self.db.get_resource(resource_type)
        if current is None:
            raise TaskOutcomeError("resource_update.type", "not_found", status_code=404)
        if current.capacity_known and amount > current.capacity:
            raise TaskOutcomeError(
                "resource_update.amount", "capacity_below_remaining"
            )
        result: dict[str, Any] = {"type": resource_type, "amount": amount}
        for field in ("consumption", "intake"):
            raw = value.get(field)
            if raw not in (None, ""):
                try:
                    result[field] = ResourceManager.validate_value(field, raw)
                except ResourceValidationError as exc:
                    raise TaskOutcomeError(
                        f"resource_update.{exc.field}", exc.reason
                    ) from exc
        return result

    @staticmethod
    def _expected_resource_update(source_ref: str) -> ResourceType | None:
        for resource_type in ResourceType:
            if any(
                marker in source_ref
                for marker in (
                    f"survival-plan-{resource_type.value}-priority",
                    f"survival-plan-{resource_type.value}-capacity",
                )
            ):
                return resource_type
        return None
