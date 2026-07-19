"""Traceable task outcomes and deterministic reassessment (SHA-243)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from allspark.core.database import Database
from allspark.core.i18n import mark
from allspark.core.models import ResourceType, TaskStatus
from allspark.services.initial_assessment import (
    InitialAssessmentDraftValidationError,
    _draft_fact,
    _draft_threats,
)
from allspark.services.resource_manager import ResourceManager, ResourceValidationError

logger = logging.getLogger(__name__)


class TaskOutcomeError(ValueError):
    def __init__(
        self,
        field: str,
        code: str,
        *,
        status_code: int = 422,
        context: dict[str, Any] | None = None,
    ):
        self.field = field
        self.code = code
        self.status_code = status_code
        self.context = context or {}
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
        fact_update: Any = None,
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
            persisted_evidence = list(dict.fromkeys([*task.evidence, *normalized_evidence]))
        normalized_update = self._resource_update(resource_update)
        normalized_fact = self._fact_update(fact_update)
        information_gap_fields = self._information_gap_fields(task.source_ref)
        if (
            status == TaskStatus.COMPLETED.value
            and task.source == "survival_plan"
            and not normalized_evidence
            and normalized_update is None
            and normalized_fact is None
        ):
            raise TaskOutcomeError("evidence", "required")
        if status == TaskStatus.COMPLETED.value and information_gap_fields:
            self._validate_information_gap_completion(
                information_gap_fields,
                resource_update=normalized_update,
                fact_update=normalized_fact,
            )
        elif normalized_fact is not None:
            raise TaskOutcomeError("fact_update", "not_applicable")
        expected_resource = self._expected_resource_update(task.source_ref)
        if status == TaskStatus.COMPLETED.value and expected_resource:
            if normalized_update is None:
                raise TaskOutcomeError("resource_update", "required")
            if normalized_update["type"] != expected_resource:
                raise TaskOutcomeError(
                    "resource_update.type",
                    "task_mismatch",
                    context={
                        "expected_resource": expected_resource.value,
                        "received_resource": normalized_update["type"].value,
                    },
                )
        if normalized_update is not None and confirm_resource_update is not True:
            raise TaskOutcomeError(
                "confirm_resource_update",
                "confirmation_required",
                status_code=409,
            )

        old_plan = self.db.get_survival_plan(active_only=True)
        previous_primary_action_id = (old_plan.accepted_action_id if old_plan is not None else None) or None
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
                    raise TaskOutcomeError(f"resource_update.{exc.field}", exc.reason) from exc
                self._clear_confirmed_unknown_fields(self._resource_update_fields(normalized_update))

            if normalized_fact is not None:
                self._apply_fact_update(normalized_fact)

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
            new_primary_action_id = candidates[0]
            self.db.replace_active_survival_plan(plan, accepted_action_id=new_primary_action_id, commit=False)
            next_task = self.mission_planner.create_task_from_active_plan(self.survival_plan, commit=False)

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
        if rule_engine is not None and hasattr(rule_engine, "invalidate_assessment_cache"):
            rule_engine.invalidate_assessment_cache()

        plan_data_changed = old_plan is None or old_plan.fingerprint != plan.fingerprint
        primary_action_changed = previous_primary_action_id != new_primary_action_id
        return {
            "task": saved,
            "plan": plan,
            "plan_changed": plan_data_changed,
            "plan_data_changed": plan_data_changed,
            "previous_primary_action_id": previous_primary_action_id,
            "new_primary_action_id": new_primary_action_id,
            "primary_action_changed": primary_action_changed,
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
            amount = ResourceManager.validate_value("amount", value.get("amount"))
        except ResourceValidationError as exc:
            raise TaskOutcomeError(f"resource_update.{exc.field}", exc.reason) from exc
        current = self.db.get_resource(resource_type)
        if current is None:
            raise TaskOutcomeError("resource_update.type", "not_found", status_code=404)
        if current.capacity_known and amount > current.capacity:
            raise TaskOutcomeError("resource_update.amount", "capacity_below_remaining")
        result: dict[str, Any] = {"type": resource_type, "amount": amount}
        for field in ("consumption", "intake"):
            raw = value.get(field)
            if raw not in (None, ""):
                try:
                    result[field] = ResourceManager.validate_value(field, raw)
                except ResourceValidationError as exc:
                    raise TaskOutcomeError(f"resource_update.{exc.field}", exc.reason) from exc
        return result

    @staticmethod
    def _fact_update(value: Any) -> dict[str, Any] | None:
        if value in (None, {}):
            return None
        if not isinstance(value, dict):
            raise TaskOutcomeError("fact_update", "invalid_object")
        field = value.get("field")
        if not isinstance(field, str) or not field.strip():
            raise TaskOutcomeError("fact_update.field", "required")
        field = field.strip()
        supported_facts = {"people_count", "health", "urgency", "shelter"}
        supported_resource_facts = {
            f"{resource.value}.{leaf}"
            for resource in ResourceType
            for leaf in ("amount", "consumption", "intake", "rate_basis", "as_of")
        }
        if field not in supported_facts | {"threats"} | supported_resource_facts:
            raise TaskOutcomeError("fact_update.field", "invalid_choice")

        status = value.get("status")
        if status == "unknown":
            if value.get("confirm_unknown") is not True:
                raise TaskOutcomeError("fact_update.confirm_unknown", "confirmation_required", status_code=409)
            return {"field": field, "status": "unknown", "confirm_unknown": True}
        if "." in field:
            raise TaskOutcomeError("fact_update.field", "use_resource_update")

        try:
            if field == "threats":
                normalized = _draft_threats(value)
            else:
                normalized = _draft_fact(value, field)
        except InitialAssessmentDraftValidationError as exc:
            raise TaskOutcomeError(f"fact_update.{exc.field}", exc.code) from exc
        if not normalized or normalized.get("status") == "unknown":
            raise TaskOutcomeError("fact_update.status", "invalid_choice")
        return {"field": field, **normalized}

    def _information_gap_fields(self, source_ref: str) -> list[str]:
        if not source_ref or ":" not in source_ref:
            return []
        plan_id, action_ref = source_ref.split(":", 1)
        action_id = action_ref.split(":follow-up-", 1)[0]
        plan = self.db.get_survival_plan(plan_id=plan_id)
        if plan is not None:
            action = next((item for item in plan.actions if item.id == action_id), None)
            if action is not None:
                return list(
                    dict.fromkeys(
                        str(item["field"])
                        for item in action.evidence
                        if item.get("kind") == "information_gap" and item.get("field")
                    )
                )
        marker = "survival-plan-gap-"
        if marker in action_id:
            return [action_id.split(marker, 1)[1]]
        return []

    def _validate_information_gap_completion(
        self,
        expected_fields: list[str],
        *,
        resource_update: dict[str, Any] | None,
        fact_update: dict[str, Any] | None,
    ) -> None:
        if resource_update is None and fact_update is None:
            raise TaskOutcomeError(
                "fact_update",
                "information_gap_update_required",
                context={"expected_fields": expected_fields, "received_fields": []},
            )

        received_fields: list[str] = []
        if resource_update is not None:
            resource_fields = self._resource_update_fields(resource_update)
            received_fields.extend(resource_fields)
            if not any(
                self._fields_correspond(expected, received)
                for expected in expected_fields
                for received in resource_fields
            ):
                raise TaskOutcomeError(
                    "resource_update.type",
                    "information_gap_mismatch",
                    context={
                        "expected_fields": expected_fields,
                        "received_fields": resource_fields,
                    },
                )
        if fact_update is not None:
            received_field = str(fact_update["field"])
            received_fields.append(received_field)
            if not any(self._fields_correspond(expected, received_field) for expected in expected_fields):
                raise TaskOutcomeError(
                    "fact_update.field",
                    "information_gap_mismatch",
                    context={
                        "expected_fields": expected_fields,
                        "received_fields": received_fields,
                    },
                )

    @staticmethod
    def _fields_correspond(expected: str, received: str) -> bool:
        return expected == received or expected.startswith(f"{received}.") or received.startswith(f"{expected}.")

    @staticmethod
    def _resource_update_fields(update: dict[str, Any]) -> list[str]:
        domain = update["type"].value
        fields = [f"{domain}.amount", f"{domain}.as_of", f"{domain}.rate_basis"]
        fields.extend(f"{domain}.{field}" for field in ("consumption", "intake") if field in update)
        return fields

    def _apply_fact_update(self, update: dict[str, Any]) -> None:
        field = str(update["field"])
        if update["status"] == "unknown":
            self.db.save_survivor_state(
                f"confirmed_unknown:{field}",
                datetime.now(timezone.utc).isoformat(),
                commit=False,
            )
            return

        self._clear_confirmed_unknown_fields([field])
        if field == "threats":
            self.db.save_survivor_state("threats_status", str(update["status"]), commit=False)
            self.db.save_survivor_state("threats", ",".join(update.get("values", [])), commit=False)
            return
        self.db.save_survivor_state(field, str(update["value"]), commit=False)
        self.db.save_survivor_state(f"{field}_status", "known", commit=False)

    def _clear_confirmed_unknown_fields(self, fields: list[str]) -> None:
        self.db.conn.executemany(
            "DELETE FROM survivor_state WHERE key=?",
            [(f"confirmed_unknown:{field}",) for field in fields],
        )

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
