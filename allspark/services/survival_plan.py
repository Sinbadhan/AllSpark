"""Deterministic, offline 24-hour survival planning (SHA-239)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from allspark.core.database import Database
from allspark.core.i18n import MESSAGES, t
from allspark.core.models import (
    RESOURCE_UNITS,
    PlanAction,
    Resource,
    ResourceType,
    SurvivalPlan,
)
from allspark.services.resource_manager import ResourceManager
from allspark.services.survival_engine import evaluate_phase_truth


class SurvivalPlanValidationError(ValueError):
    def __init__(self, field: str, code: str):
        self.field = field
        self.code = code
        super().__init__(f"{field}: {code}")


_GAP_ORDER = (
    "urgency",
    "health",
    "threats",
    "shelter",
    "water",
    "food",
    "people_count",
    "fire",
    "power",
    "storage",
)


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class SurvivalPlanService:
    """Generate and persist a plan without LLM, network, or mutable Tasks."""

    def __init__(self, db: Database, resource_manager: ResourceManager):
        self.db = db
        self.resource_manager = resource_manager

    def generate(
        self, assessment: dict[str, Any], *, now: datetime | None = None
    ) -> SurvivalPlan:
        snapshot_now = now or datetime.now(timezone.utc)
        resources = self._assessment_resources(assessment)
        return self._generate_from_facts(
            assessment,
            resources,
            snapshot_now=snapshot_now,
        )

    def generate_current(self, *, now: datetime | None = None) -> SurvivalPlan:
        """Reassess persisted facts without refreshing their observation time."""
        snapshot_now = now or datetime.now(timezone.utc)
        resources = self.resource_manager.get_all_resources()
        assessment = self._current_assessment(resources)
        return self._generate_from_facts(
            assessment,
            resources,
            snapshot_now=snapshot_now,
        )

    def _generate_from_facts(
        self,
        assessment: dict[str, Any],
        resources: list[Resource],
        *,
        snapshot_now: datetime,
    ) -> SurvivalPlan:
        phase, phase_missing, phase_stale = evaluate_phase_truth(
            resources, self.resource_manager, now=snapshot_now
        )
        gaps = self._gap_domains(resources, assessment, now=snapshot_now)
        missing_fields = [
            item["field"]
            for domain in _GAP_ORDER
            for item in gaps.get(domain, [])
            if item["status"] == "unknown"
        ]
        stale_fields = [
            item["field"]
            for domain in _GAP_ORDER
            for item in gaps.get(domain, [])
            if item["status"] == "stale"
        ]
        actions = self._actions(
            assessment,
            resources,
            phase=phase,
            gaps=gaps,
            now=snapshot_now,
        )
        assessment_contract = {
            key: value for key, value in assessment.items() if key != "confirmed"
        }
        assessment_hash = _canonical_hash(assessment_contract)
        semantics = {
            "assessment_hash": assessment_hash,
            "phase": phase,
            "phase_status": "known" if phase is not None else "unknown",
            "phase_missing_fields": phase_missing,
            "phase_stale_fields": phase_stale,
            "missing_fields": missing_fields,
            "stale_fields": stale_fields,
            "actions": [self._action_contract(action) for action in actions],
            "horizon_hours": 24,
        }
        fingerprint = _canonical_hash(semantics)
        return SurvivalPlan(
            id=f"survival-plan-{fingerprint.removeprefix('sha256:')[:20]}",
            assessment_hash=assessment_hash,
            fingerprint=fingerprint,
            phase=phase,
            phase_status="known" if phase is not None else "unknown",
            missing_fields=missing_fields,
            stale_fields=stale_fields,
            actions=actions,
            created_at=snapshot_now.isoformat(),
        )

    def _current_assessment(self, resources: list[Resource]) -> dict[str, Any]:
        survivor = self.db.get_survivor_state()

        def fact(name: str) -> dict[str, Any]:
            status = survivor.get(f"{name}_status", "unknown")
            value = survivor.get(name)
            if status != "known" or value in (None, "", "unknown"):
                return {"status": "unknown", "value": None}
            return {"status": "known", "value": value}

        people_status = survivor.get("people_count_status", "unknown")
        people_value: int | None = None
        if people_status == "known":
            try:
                people_value = int(survivor.get("people_count", ""))
            except (TypeError, ValueError):
                people_value = None
        if people_value is None:
            people_value = next(
                (
                    resource.people_count
                    for resource in resources
                    if resource.people_count_known and resource.people_count > 0
                ),
                None,
            )
            people_status = "known" if people_value is not None else "unknown"

        threat_status = survivor.get("threats_status", "unknown")
        threat_values = [
            value
            for value in survivor.get("threats", "").split(",")
            if value
        ]
        if threat_status not in {"none", "selected"}:
            threat_status = "unknown"
            threat_values = []

        resource_contract = {}
        for resource in resources:
            rates_known = (
                resource.consumption_known
                and resource.intake_known
                and resource.rate_basis == "group_total"
            )
            resource_contract[resource.type.value] = {
                "status": "known" if resource.amount_known else "unknown",
                "amount": resource.current_amount if resource.amount_known else None,
                "unit": resource.unit,
                "rates": {
                    "status": "estimate" if rates_known else "unknown",
                    "basis": resource.rate_basis if rates_known else None,
                    "daily_consumption": (
                        resource.daily_consumption if rates_known else None
                    ),
                    "daily_intake": resource.daily_intake if rates_known else None,
                },
                "source": resource.source,
                "as_of": resource.as_of,
            }

        observed_times = sorted(
            resource.as_of for resource in resources if resource.as_of
        )
        return {
            "people_count": {
                "status": people_status,
                "value": people_value,
            },
            "health": fact("health"),
            "urgency": fact("urgency"),
            "shelter": fact("shelter"),
            "threats": {"status": threat_status, "values": threat_values},
            "resources": resource_contract,
            "as_of": observed_times[-1] if observed_times else "",
            "confirmed": True,
        }

    def validate_selection(
        self,
        plan: SurvivalPlan,
        *,
        plan_id: str,
        accepted_action_id: str,
    ) -> None:
        if plan_id != plan.id:
            raise SurvivalPlanValidationError("plan_id", "stale_plan")
        if accepted_action_id not in self.primary_candidate_ids(plan):
            raise SurvivalPlanValidationError(
                "primary_action_id", "invalid_primary_action"
            )

    def persist_draft(
        self,
        plan: SurvivalPlan,
        *,
        plan_id: str,
        accepted_action_id: str,
        commit: bool = True,
    ) -> SurvivalPlan:
        self.validate_selection(
            plan, plan_id=plan_id, accepted_action_id=accepted_action_id
        )
        plan.accepted_action_id = accepted_action_id
        plan.status = "draft"
        self.db.save_survival_plan(plan, commit=commit)
        return plan

    @staticmethod
    def primary_candidate_ids(plan: SurvivalPlan) -> list[str]:
        if not plan.actions:
            return []
        minimum = min(action.priority for action in plan.actions)
        return [action.id for action in plan.actions if action.priority == minimum]

    def payload(
        self, plan: SurvivalPlan, *, language: str | None = None
    ) -> dict[str, Any]:
        return {
            "id": plan.id,
            "assessment_hash": plan.assessment_hash,
            "fingerprint": plan.fingerprint,
            "phase": plan.phase,
            "phase_status": plan.phase_status,
            "phase_description": self._translate(
                f"phase_desc_{plan.phase}"
                if plan.phase is not None else "phase_desc_unknown",
                language=language,
            ),
            "missing_fields": plan.missing_fields,
            "stale_fields": plan.stale_fields,
            "accepted_action_id": plan.accepted_action_id or None,
            "status": plan.status,
            "horizon_hours": plan.horizon_hours,
            "primary_candidate_ids": self.primary_candidate_ids(plan),
            "actions": [
                self._render_action(action, language=language)
                for action in plan.actions
            ],
        }

    @staticmethod
    def _translate(
        key: str, *, language: str | None = None, **kwargs: Any
    ) -> str:
        if language not in MESSAGES:
            return t(key, **kwargs)
        message = MESSAGES[language].get(key, key)
        try:
            return message.format(**kwargs)
        except (KeyError, IndexError):
            return message

    @staticmethod
    def _action_contract(action: PlanAction) -> dict[str, Any]:
        return {
            "id": action.id,
            "domain": action.domain,
            "priority": action.priority,
            "title_key": action.title_key,
            "why_now": action.why_now,
            "evidence": action.evidence,
            "prerequisites": action.prerequisites,
            "risk": action.risk,
            "done_when": action.done_when,
            "reassess_at": action.reassess_at,
            "order": action.order,
        }

    @staticmethod
    def _render_action(
        action: PlanAction, *, language: str | None = None
    ) -> dict[str, Any]:
        domain_label = SurvivalPlanService._translate(
            "assessment_title"
            if action.domain == "assessment"
            else f"assessment_field_{action.domain}",
            language=language,
        )
        return {
            **SurvivalPlanService._action_contract(action),
            "status": action.status,
            "title": SurvivalPlanService._translate(
                action.title_key, language=language, domain=domain_label
            ),
            "why_now_text": SurvivalPlanService._translate(
                action.why_now, language=language, domain=domain_label
            ),
            "prerequisite_texts": [
                SurvivalPlanService._translate(
                    key, language=language, domain=domain_label
                )
                for key in action.prerequisites
            ],
            "risk_text": SurvivalPlanService._translate(
                action.risk, language=language, domain=domain_label
            ),
            "done_when_text": SurvivalPlanService._translate(
                action.done_when, language=language, domain=domain_label
            ),
            "evidence_texts": [
                SurvivalPlanService._render_evidence(item, language=language)
                for item in action.evidence
            ],
            "reassess_at_text": SurvivalPlanService._translate(
                "survival_plan_reassess_1h"
                if action.reassess_at == "PT1H"
                else "survival_plan_reassess_4h"
                if action.reassess_at == "PT4H"
                else "survival_plan_reassess_24h",
                language=language,
            ),
        }

    @staticmethod
    def _render_evidence(evidence: dict[str, Any], *, language: str | None) -> str:
        kind = evidence.get("kind")
        source = evidence.get("source", "unknown")
        source_label = SurvivalPlanService._translate(
            f"resource_source_{source}", language=language
        )
        if kind == "resource_snapshot" and "remaining_hours" in evidence:
            return SurvivalPlanService._translate(
                "survival_plan_evidence_resource_formula",
                language=language,
                amount=evidence.get("amount", "?"),
                unit=evidence.get("unit", ""),
                consumption=evidence.get("daily_consumption", "?"),
                intake=evidence.get("daily_intake", "?"),
                hours=evidence["remaining_hours"],
                threshold=evidence.get("threshold_hours", "?"),
                as_of=evidence.get("as_of", ""),
                source=source_label,
            )
        if kind == "resource_snapshot":
            return SurvivalPlanService._translate(
                "survival_plan_evidence_resource_amount",
                language=language,
                amount=evidence.get("amount", "?"),
                unit=evidence.get("unit", ""),
                as_of=evidence.get("as_of", ""),
                source=source_label,
            )
        if kind == "reviewed_workflow":
            return SurvivalPlanService._translate(
                "survival_plan_evidence_fact",
                language=language,
                field=SurvivalPlanService._translate(
                    "assessment_field_reviewed_workflow", language=language
                ),
                value=SurvivalPlanService._translate(
                    "survival_plan_evidence_status_review_gated", language=language
                ),
            )
        if kind == "assessment_state":
            phase = evidence.get("phase")
            return SurvivalPlanService._translate(
                "survival_plan_evidence_fact",
                language=language,
                field=SurvivalPlanService._translate(
                    "assessment_title", language=language
                ),
                value=SurvivalPlanService._translate(
                    f"phase_desc_{phase}" if phase is not None else "phase_desc_unknown",
                    language=language,
                ),
            )
        raw_field = evidence.get("field", kind or "unknown")
        field_parts = str(raw_field).split(".", 1)
        field_label = SurvivalPlanService._translate(
            f"assessment_field_{field_parts[0]}", language=language
        )
        if len(field_parts) == 2:
            detail_key = {
                "amount": "web_resource_edit_amount",
                "consumption": "web_resource_edit_consumption",
                "intake": "web_resource_edit_intake",
                "rate_basis": "web_init_group_total_basis",
                "as_of": "assessment_field_as_of",
            }.get(field_parts[1], "assessment_field_information_gap")
            field_label = f"{field_label} / {SurvivalPlanService._translate(detail_key, language=language)}"
        raw_value = evidence.get(
            "value", evidence.get("status", evidence.get("phase_status", "unknown"))
        )
        if isinstance(raw_value, list):
            value_label = ", ".join(
                SurvivalPlanService._translate(
                    f"q_threat_{value}", language=language
                )
                for value in raw_value
            )
        elif kind == "assessment_fact" and isinstance(raw_value, str):
            value_key = {
                ("urgency", "immediate_danger"): "q_urgency_immediate",
                ("health", "serious_injury"): "q_health_serious",
            }.get((field_parts[0], raw_value), f"q_{field_parts[0]}_{raw_value}")
            value_label = SurvivalPlanService._translate(
                value_key, language=language
            )
        else:
            value_label = SurvivalPlanService._translate(
                f"survival_plan_evidence_status_{raw_value}", language=language
            )
        return SurvivalPlanService._translate(
            "survival_plan_evidence_fact",
            language=language,
            field=field_label,
            value=value_label,
        )

    def _assessment_resources(
        self, assessment: dict[str, Any]
    ) -> list[Resource]:
        people = assessment["people_count"]
        people_known = people["status"] == "known"
        result = []
        for resource_type in ResourceType:
            item = assessment["resources"][resource_type.value]
            rates = item["rates"]
            rate_known = rates["status"] == "estimate"
            resource = Resource(
                type=resource_type,
                current_amount=item["amount"] if item["status"] == "known" else 0,
                unit=RESOURCE_UNITS[resource_type],
                daily_consumption=(
                    rates["daily_consumption"] if rate_known else 0
                ),
                daily_intake=rates["daily_intake"] if rate_known else 0,
                rate_basis=rates.get("basis", "unknown") if rate_known else "unknown",
                amount_known=item["status"] == "known",
                consumption_known=rate_known,
                intake_known=rate_known,
                source="user_input",
                people_count=people["value"] if people_known else 1,
                people_count_known=people_known,
                as_of=assessment["as_of"],
            )
            resource.estimated_remaining_hours = (
                self.resource_manager.estimate_remaining(resource)
            )
            result.append(resource)
        return result

    def _gap_domains(
        self,
        resources: list[Resource],
        assessment: dict[str, Any],
        *,
        now: datetime,
    ) -> dict[str, list[dict[str, str]]]:
        gaps: dict[str, list[dict[str, str]]] = {}
        for domain in ("people_count", "health", "urgency", "shelter"):
            if assessment[domain]["status"] == "unknown":
                gaps[domain] = [{"field": domain, "status": "unknown"}]
        if assessment["threats"]["status"] == "unknown":
            gaps["threats"] = [{"field": "threats", "status": "unknown"}]
        for resource in resources:
            domain = resource.type.value
            fields: list[dict[str, str]] = []
            if not resource.amount_known:
                fields.append({"field": f"{domain}.amount", "status": "unknown"})
            if not resource.consumption_known:
                fields.append(
                    {"field": f"{domain}.consumption", "status": "unknown"}
                )
            if not resource.intake_known:
                fields.append({"field": f"{domain}.intake", "status": "unknown"})
            if resource.rate_basis != "group_total":
                fields.append(
                    {"field": f"{domain}.rate_basis", "status": "unknown"}
                )
            if not self.resource_manager.is_snapshot_current(resource, now=now):
                fields.append({"field": f"{domain}.as_of", "status": "stale"})
            if fields:
                gaps[domain] = fields
        return gaps

    def _actions(
        self,
        assessment: dict[str, Any],
        resources: list[Resource],
        *,
        phase: int | None,
        gaps: dict[str, list[dict[str, str]]],
        now: datetime,
    ) -> list[PlanAction]:
        actions: list[PlanAction] = []
        for domain in _GAP_ORDER:
            evidence = gaps.get(domain)
            if evidence:
                actions.append(
                    self._make_action(
                        f"survival-plan-gap-{domain}",
                        domain,
                        1
                        if domain
                        in {"urgency", "health", "threats", "shelter", "water", "food"}
                        else 3,
                        "survival_plan_gap",
                        evidence=[
                            {"kind": "information_gap", **item} for item in evidence
                        ],
                        reassess_at="PT1H",
                    )
                )

        facts = assessment
        if (
            facts["urgency"]["status"] == "known"
            and facts["urgency"]["value"] == "immediate_danger"
        ):
            actions.append(
                self._fact_action(
                    "immediate_danger", "urgency", 0, "immediate_danger", "PT1H"
                )
            )
        if (
            facts["health"]["status"] == "known"
            and facts["health"]["value"] in {"serious_injury", "critical"}
        ):
            actions.append(
                self._fact_action(
                    "health_help", "health", 0, facts["health"]["value"], "PT1H"
                )
            )
        if facts["threats"]["status"] == "selected":
            actions.append(
                self._make_action(
                    "survival-plan-threat-review",
                    "threats",
                    0,
                    "survival_plan_threat_review",
                    evidence=[
                        {
                            "kind": "assessment_fact",
                            "field": "threats",
                            "status": "known",
                            "value": facts["threats"]["values"],
                        },
                        {
                            "kind": "reviewed_workflow",
                            "workflow": "immediate_danger",
                            "review_status": "review_gated",
                        },
                    ],
                    reassess_at="PT1H",
                )
            )
        if (
            facts["shelter"]["status"] == "known"
            and facts["shelter"]["value"] in {"none", "open_air"}
        ):
            actions.append(
                self._fact_action(
                    "shelter", "shelter", 0, facts["shelter"]["value"], "PT1H"
                )
            )

        for resource in resources:
            if not self.resource_manager.is_snapshot_current(resource, now=now):
                continue
            domain = resource.type.value
            limits = {"water": 72, "food": 48, "power": 24}
            status = "unknown"
            if self.resource_manager.has_complete_rate_data(resource):
                status = (
                    "sustained"
                    if resource.daily_consumption <= resource.daily_intake
                    else "finite"
                )
            if domain in limits and status == "finite":
                hours = resource.estimated_remaining_hours
                if hours < limits[domain]:
                    actions.append(
                        self._make_action(
                            f"survival-plan-{domain}-priority",
                            domain,
                            1,
                            "survival_plan_resource_priority",
                            evidence=[
                                {
                                    "kind": "resource_snapshot",
                                    "resource": domain,
                                    "remaining_status": "finite",
                                    "amount": resource.current_amount,
                                    "unit": resource.unit,
                                    "daily_consumption": resource.daily_consumption,
                                    "daily_intake": resource.daily_intake,
                                    "remaining_hours": round(hours, 3),
                                    "threshold_hours": limits[domain],
                                    "as_of": resource.as_of,
                                    "source": resource.source,
                                }
                            ],
                            reassess_at="PT1H",
                        )
                    )
            if (
                domain == "fire"
                and resource.amount_known
                and resource.current_amount < 5
            ):
                actions.append(
                    self._make_action(
                        "survival-plan-fire-capacity",
                        "fire",
                        2,
                        "survival_plan_fire_capacity",
                        evidence=[
                            {
                                "kind": "resource_snapshot",
                                "resource": "fire",
                                "amount": resource.current_amount,
                                "unit": resource.unit,
                                "as_of": resource.as_of,
                                "source": resource.source,
                            }
                        ],
                        reassess_at="PT4H",
                    )
                )

        if not actions:
            actions.append(
                self._make_action(
                    "survival-plan-maintain-review",
                    "assessment",
                    2,
                    "survival_plan_maintain_review",
                    evidence=[
                        {
                            "kind": "assessment_state",
                            "phase": phase,
                            "phase_status": "known" if phase is not None else "unknown",
                            "as_of": facts["as_of"],
                        }
                    ],
                    reassess_at="PT4H",
                )
            )
        actions.sort(
            key=lambda action: (
                action.priority,
                _GAP_ORDER.index(action.domain)
                if action.domain in _GAP_ORDER
                else len(_GAP_ORDER),
                action.id,
            )
        )
        for index, action in enumerate(actions):
            action.order = index
        return actions

    @staticmethod
    def _fact_action(
        action: str,
        domain: str,
        priority: int,
        value: str,
        reassess_at: str,
    ) -> PlanAction:
        evidence: list[dict[str, Any]] = [
            {
                "kind": "assessment_fact",
                "field": domain,
                "status": "known",
                "value": value,
            }
        ]
        if action in {"immediate_danger", "health_help", "shelter"}:
            evidence.append(
                {
                    "kind": "reviewed_workflow",
                    "workflow": "immediate_danger",
                    "review_status": "review_gated",
                }
            )
        return SurvivalPlanService._make_action(
            f"survival-plan-{action}",
            domain,
            priority,
            f"survival_plan_{action}",
            evidence=evidence,
            reassess_at=reassess_at,
        )

    @staticmethod
    def _make_action(
        action_id: str,
        domain: str,
        priority: int,
        key_prefix: str,
        *,
        evidence: list[dict[str, Any]],
        reassess_at: str,
    ) -> PlanAction:
        return PlanAction(
            id=action_id,
            domain=domain,
            priority=priority,
            title_key=f"{key_prefix}_title",
            why_now=f"{key_prefix}_why",
            evidence=evidence,
            prerequisites=[f"{key_prefix}_prerequisite"],
            risk=f"{key_prefix}_risk",
            done_when=f"{key_prefix}_done",
            reassess_at=reassess_at,
        )
