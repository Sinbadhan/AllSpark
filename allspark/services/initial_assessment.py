"""Shared first-run assessment contract for Web and CLI (SHA-238)."""

from __future__ import annotations

from typing import Any

from allspark.core.database import Database
from allspark.core.models import RESOURCE_UNITS, ResourceType, Task
from allspark.services.resource_manager import (
    ResourceManager,
    ResourceValidationError,
)

CRITICAL_FACTS = ("people_count", "health", "urgency", "shelter")
RESOURCE_TYPES = tuple(resource.value for resource in ResourceType)
_ALLOWED_FACT_VALUES = {
    "health": {
        "healthy",
        "minor_injury",
        "serious_injury",
        "chronic_condition",
        "critical",
    },
    "urgency": {
        "immediate_danger",
        "stable_but_urgent",
        "stable",
        "comfortable",
    },
    "shelter": {
        "permanent_building",
        "temporary_shelter",
        "vehicle",
        "open_air",
        "underground",
        "none",
    },
}
_ALLOWED_THREATS = {
    "extreme_weather",
    "wildlife",
    "contamination",
    "structural_collapse",
    "flooding",
    "fire_risk",
    "human_threat",
    "disease",
}

_GAP_PRIORITIES = {
    "health": 1,
    "shelter": 1,
    "water": 1,
    "food": 1,
    "threats": 1,
    "urgency": 1,
    "people_count": 2,
    "power": 3,
    "fire": 3,
    "storage": 3,
    "power_rate": 3,
    "water_rate": 1,
    "food_rate": 1,
    "fire_rate": 3,
    "storage_rate": 3,
}


class InitialAssessmentValidationError(ValueError):
    def __init__(self, errors: list[dict[str, str]]):
        self.errors = errors
        super().__init__("Initial assessment is incomplete or invalid")


def _error(errors: list[dict[str, str]], field: str, code: str) -> None:
    errors.append({"field": field, "code": code})


def _fact(
    payload: Any,
    field: str,
    errors: list[dict[str, str]],
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        _error(errors, field, "explicit_status_required")
        return None
    status = payload.get("status")
    if status == "unknown":
        if payload.get("value") is not None:
            _error(errors, field, "values_not_allowed")
            return None
        return {"status": "unknown", "value": None}
    if status != "known":
        _error(errors, field, "explicit_status_required")
        return None
    value = payload.get("value")
    if field == "people_count":
        try:
            normalized = ResourceManager.validate_people_count(value)
        except ResourceValidationError as exc:
            _error(errors, field, exc.reason)
            return None
        return {"status": "known", "value": normalized}
    if not isinstance(value, str) or value not in _ALLOWED_FACT_VALUES[field]:
        _error(errors, field, "invalid_choice")
        return None
    return {"status": "known", "value": value}


def _threats(payload: Any, errors: list[dict[str, str]]) -> dict[str, Any] | None:
    field = "threats"
    if not isinstance(payload, dict):
        _error(errors, field, "explicit_status_required")
        return None
    status = payload.get("status")
    if status in {"none", "unknown"}:
        values = payload.get("values", [])
        if values not in (None, []):
            _error(errors, field, "values_not_allowed")
            return None
        return {"status": status, "values": []}
    if status != "selected":
        _error(errors, field, "threat_status_required")
        return None
    values = payload.get("values")
    if not isinstance(values, list) or not values:
        _error(errors, field, "threat_selection_required")
        return None
    if any(not isinstance(value, str) or value not in _ALLOWED_THREATS for value in values):
        _error(errors, field, "invalid_choice")
        return None
    return {"status": "selected", "values": list(dict.fromkeys(values))}


def _resource(
    payload: Any,
    resource_type: ResourceType,
    errors: list[dict[str, str]],
) -> dict[str, Any] | None:
    field = f"resources.{resource_type.value}"
    if not isinstance(payload, dict):
        _error(errors, field, "explicit_status_required")
        return None
    status = payload.get("status")
    rates_payload = payload.get("rates")
    rates_field = f"{field}.rates"
    rates: dict[str, Any] | None = None
    if not isinstance(rates_payload, dict):
        _error(errors, rates_field, "explicit_status_required")
    elif rates_payload.get("status") == "unknown":
        if any(
            rates_payload.get(key) is not None
            for key in ("daily_consumption", "daily_intake")
        ):
            _error(errors, rates_field, "values_not_allowed")
        else:
            rates = {
                "status": "unknown",
                "daily_consumption": None,
                "daily_intake": None,
            }
    elif rates_payload.get("status") == "estimate":
        if rates_payload.get("basis") != "group_total":
            _error(errors, f"{rates_field}.basis", "invalid_rate_basis")
        try:
            consumption = ResourceManager.validate_value(
                "daily_consumption", rates_payload.get("daily_consumption")
            )
            intake = ResourceManager.validate_value(
                "daily_intake", rates_payload.get("daily_intake")
            )
        except ResourceValidationError as exc:
            _error(errors, f"{rates_field}.{exc.field}", exc.reason)
        else:
            rates = {
                "status": "estimate",
                "basis": "group_total",
                "daily_consumption": consumption,
                "daily_intake": intake,
            }
    else:
        _error(errors, rates_field, "explicit_status_required")

    if status == "unknown":
        if payload.get("amount") is not None or payload.get("confirm_outlier") not in (
            None,
            False,
        ):
            _error(errors, field, "values_not_allowed")
            return None
        return {
            "status": "unknown",
            "amount": None,
            "confirm_outlier": False,
            "rates": rates,
        }
    if status != "known":
        _error(errors, field, "explicit_status_required")
        return None
    try:
        amount = ResourceManager.validate_value("amount", payload.get("amount"))
    except ResourceValidationError as exc:
        _error(errors, f"{field}.amount", exc.reason)
        return None
    confirm_outlier = payload.get("confirm_outlier", False)
    if not isinstance(confirm_outlier, bool):
        _error(errors, f"{field}.confirm_outlier", "not_boolean")
        return None
    if (
        amount > ResourceManager.RESOURCE_SOFT_MAX[resource_type]
        and not confirm_outlier
    ):
        _error(errors, f"{field}.amount", "outlier_confirmation")
        return None
    if rates is not None and rates["status"] == "estimate":
        rate_values = (rates["daily_consumption"], rates["daily_intake"])
        if (
            any(
                value > ResourceManager.RESOURCE_SOFT_MAX[resource_type]
                for value in rate_values
            )
            and not confirm_outlier
        ):
            _error(errors, f"{field}.rates", "outlier_confirmation")
            return None
    return {
        "status": "known",
        "amount": amount,
        "confirm_outlier": confirm_outlier,
        "rates": rates,
    }


def validate_initial_assessment(
    payload: Any, *, require_confirmation: bool = True
) -> dict[str, Any]:
    """Validate every critical domain before any initialization draft write."""
    if not isinstance(payload, dict):
        raise InitialAssessmentValidationError(
            [{"field": "assessment", "code": "object_required"}]
        )
    errors: list[dict[str, str]] = []
    normalized: dict[str, Any] = {}
    for field in CRITICAL_FACTS:
        result = _fact(payload.get(field), field, errors)
        if result is not None:
            normalized[field] = result

    threat_result = _threats(payload.get("threats"), errors)
    if threat_result is not None:
        normalized["threats"] = threat_result

    resources = payload.get("resources")
    if not isinstance(resources, dict):
        _error(errors, "resources", "object_required")
    else:
        normalized_resources: dict[str, dict[str, Any]] = {}
        for resource_type in ResourceType:
            result = _resource(
                resources.get(resource_type.value),
                resource_type,
                errors,
            )
            if result is not None:
                normalized_resources[resource_type.value] = result
        normalized["resources"] = normalized_resources

    if errors:
        raise InitialAssessmentValidationError(errors)
    try:
        normalized["as_of"] = ResourceManager.validate_as_of(payload.get("as_of"))
    except ResourceValidationError as exc:
        raise InitialAssessmentValidationError(
            [{"field": "as_of", "code": exc.reason}]
        ) from exc
    normalized["confirmed"] = payload.get("confirmed") is True
    if require_confirmation and not normalized["confirmed"]:
        raise InitialAssessmentValidationError(
            [{"field": "confirmed", "code": "confirmation_required"}]
        )
    return normalized


def assessment_gap_domains(assessment: dict[str, Any]) -> list[str]:
    gaps = [
        field
        for field in CRITICAL_FACTS
        if assessment[field]["status"] == "unknown"
    ]
    if assessment["threats"]["status"] == "unknown":
        gaps.append("threats")
    gaps.extend(
        resource
        for resource in RESOURCE_TYPES
        if assessment["resources"][resource]["status"] == "unknown"
    )
    gaps.extend(
        f"{resource}_rate"
        for resource in RESOURCE_TYPES
        if assessment["resources"][resource]["rates"]["status"] == "unknown"
    )
    return sorted(gaps, key=lambda field: _GAP_PRIORITIES[field])


def assessment_preview(assessment: dict[str, Any]) -> dict[str, Any]:
    gaps = assessment_gap_domains(assessment)
    known = [
        {"domain": field, "value": assessment[field]["value"]}
        for field in CRITICAL_FACTS
        if assessment[field]["status"] == "known"
    ]
    threats = assessment["threats"]
    if threats["status"] != "unknown":
        known.append(
            {
                "domain": "threats",
                "value": threats["values"],
                "status": threats["status"],
            }
        )
    resource_states = []
    for resource_type in ResourceType:
        resource = assessment["resources"][resource_type.value]
        estimated_rates = resource["rates"]["status"] == "estimate"
        source = (
            "mixed"
            if resource["status"] == "known" and estimated_rates
            else "estimate"
            if estimated_rates
            else "user_input"
        )
        resource_states.append(
            {
                "domain": resource_type.value,
                "amount_status": resource["status"],
                "amount": resource["amount"],
                "unit": RESOURCE_UNITS[resource_type],
                "rate_status": resource["rates"]["status"],
                "rate_basis": resource["rates"].get("basis"),
                "daily_consumption": resource["rates"]["daily_consumption"],
                "daily_intake": resource["rates"]["daily_intake"],
                "source": source,
            }
        )
        if resource["status"] == "known":
            known.append(
                {
                    "domain": resource_type.value,
                    "value": resource["amount"],
                    "unit": RESOURCE_UNITS[resource_type],
                }
            )
    return {
        "known": known,
        "unknown": gaps,
        "resources": resource_states,
        "as_of": assessment["as_of"],
        # Compatibility key retained for SHA-238 preview clients. The sibling
        # SHA-239 `plan` payload is now the sole action contract.
        "actions": [],
    }


class InitialAssessmentService:
    def __init__(self, db: Database, resource_manager: ResourceManager):
        self.db = db
        self.resource_manager = resource_manager

    def apply(self, assessment: dict[str, Any]) -> list[Task]:
        """Persist a validated assessment draft using idempotent fixed keys."""
        people = assessment["people_count"]
        people_known = people["status"] == "known"
        people_count = people["value"] if people_known else 1
        self.db.save_survivor_state(
            "people_count", str(people["value"]) if people_known else "unknown"
        )
        self.db.save_survivor_state(
            "people_count_status", "known" if people_known else "unknown"
        )
        for field in ("health", "urgency", "shelter"):
            fact = assessment[field]
            self.db.save_survivor_state(
                field, fact["value"] if fact["status"] == "known" else "unknown"
            )
            self.db.save_survivor_state(f"{field}_status", fact["status"])

        threats = assessment["threats"]
        self.db.save_survivor_state("threats_status", threats["status"])
        self.db.save_survivor_state("threats", ",".join(threats["values"]))
        self.db.save_survivor_state("assessment_version", "1")

        snapshot_time = assessment["as_of"]
        for resource_type in ResourceType:
            resource = assessment["resources"][resource_type.value]
            rates = resource["rates"]
            estimated_rates = rates["status"] == "estimate"
            source = (
                "mixed"
                if resource["status"] == "known" and estimated_rates
                else "estimate"
                if estimated_rates
                else "user_input"
            )
            self.resource_manager.update_resource(
                resource_type,
                resource["amount"],
                consumption=rates["daily_consumption"],
                intake=rates["daily_intake"],
                rate_basis=rates.get("basis", "unknown"),
                source=source,
                people_count=people_count,
                people_count_known=people_known,
                as_of=snapshot_time,
                amount_known=resource["status"] == "known",
                consumption_known=estimated_rates,
                intake_known=estimated_rates,
                capacity_known=False,
                confirm_outlier=resource["confirm_outlier"],
            )

        # Information gaps belong to the persisted 24-hour plan. Legacy gap
        # sentinels are replaced atomically only when that plan is published.
        return []
