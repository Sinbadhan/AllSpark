"""Fail-closed canonical safety-scenario audit for SHA-241.

Structural validation and deterministic regression are deliberately separate
from the release review gate.  Automated code cannot certify medical,
engineering, or survival advice; only a named reviewer with a matching
qualification and exact fixture/content hash can make a scenario eligible for
release metrics.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

from allspark.core.models import compute_content_hash
from allspark.services.knowledge_loader import (
    _TIER_FILES,
    _load_yaml,
    load_knowledge,
)

_DATA_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "safety" / "scenarios.yaml"
)

VALID_HAZARDS = {
    "biological",
    "electrical",
    "environmental",
    "explosion",
    "fire",
    "mechanical",
    "medical",
    "structural",
    "toxic",
    "unknown",
    "violence",
}
VALID_DOMAINS = {
    "assessment",
    "care",
    "environmental",
    "incident_safety",
    "medical",
    "resources",
    "shelter",
    "toxicology",
}
VALID_TRIAGE_TYPES = {
    "airway",
    "environmental_exposure",
    "incident_scene",
    "poisoning",
    "resource_shortage",
    "severe_bleeding",
    "shelter_safety",
    "unknown",
    "unresponsive_breathing",
    "vulnerable_care",
}
SCENARIO_REVIEW_STATUSES = {"pending_external_review", "approved", "rejected"}
KNOWLEDGE_REVIEW_STATUSES = {"pending_external_review", "approved", "rejected"}
QUALIFICATION_BY_HAZARD = {
    "biological": {
        "biology",
        "environmental_health",
        "emergency_medicine",
        "toxicology",
    },
    "electrical": {"electrical_engineering"},
    "environmental": {"environmental_health", "survival_operations"},
    "explosion": {"fire_safety", "mechanical_engineering"},
    "fire": {"fire_safety"},
    "mechanical": {"mechanical_engineering"},
    "medical": {"emergency_medicine", "toxicology"},
    "structural": {"structural_engineering"},
    "toxic": {"toxicology", "environmental_health"},
    "unknown": {"cross_domain_panel"},
    "violence": {"violence_prevention"},
}
QUALIFICATION_BY_DOMAIN = {
    "assessment": {"cross_domain_panel"},
    "care": {"emergency_medicine"},
    "environmental": {"emergency_medicine", "environmental_health", "survival_operations"},
    "incident_safety": {"fire_safety", "structural_engineering", "toxicology"},
    "medical": {"emergency_medicine"},
    "resources": {"environmental_health", "survival_operations"},
    "shelter": {"structural_engineering", "survival_operations"},
    "toxicology": {"toxicology"},
}
QUALIFICATION_BY_TRIAGE = {
    "airway": {"emergency_medicine"},
    "environmental_exposure": {"emergency_medicine", "environmental_health"},
    "incident_scene": {"fire_safety", "structural_engineering", "toxicology"},
    "poisoning": {"toxicology"},
    "resource_shortage": {"environmental_health", "survival_operations"},
    "severe_bleeding": {"emergency_medicine"},
    "shelter_safety": {"structural_engineering", "survival_operations"},
    "unknown": {"cross_domain_panel"},
    "unresponsive_breathing": {"emergency_medicine"},
    "vulnerable_care": {"emergency_medicine"},
}
SCENARIO_FIELDS = {
    "id",
    "scenario_revision",
    "title",
    "domain",
    "triage_type",
    "hazards",
    "known_facts",
    "explicit_unknowns",
    "runner_input",
    "expected_first_action",
    "required_questions",
    "expected_escalation",
    "reviewer_narrative",
    "forbidden_action_ids",
    "forbidden_exact_patterns",
    "allowed_tier0_entries",
    "evidence_revisions",
    "escalation_conditions",
    "completion_criteria",
    "adversarial_variants",
    "review_status",
    "reviewer_signoffs",
}
OBSERVED_FIELDS = {
    "action_id",
    "action_revision",
    "questions",
    "escalation",
    "evidence",
    "output_text",
}
_MAX_SCENARIO_BYTES = 64 * 1024
_MAX_STRING = 4096
_MAX_LIST_ITEMS = 64


class SafetyScenarioValidationError(ValueError):
    """Raised when a canonical scenario or reviewer record is malformed."""


def _string_list(value: object, field: str, *, allow_empty: bool = False) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > _MAX_LIST_ITEMS
        or (not allow_empty and not value)
    ):
        raise SafetyScenarioValidationError(f"{field} must be a bounded list")
    if any(
        not isinstance(item, str)
        or not item.strip()
        or len(item) > _MAX_STRING
        for item in value
    ):
        raise SafetyScenarioValidationError(f"{field} contains an invalid item")
    return [item.strip() for item in value]


def _iso_date(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SafetyScenarioValidationError(f"{field} is required")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise SafetyScenarioValidationError(f"{field} must be an ISO date") from exc
    return value


def scenario_content_hash(scenario: dict) -> str:
    """Hash every scenario contract field except reviewer signatures."""
    payload = {
        key: value for key, value in scenario.items() if key != "reviewer_signoffs"
    }
    canonical = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def action_contract_hash(action_id: str, action_revision: int, text: str) -> str:
    """Bind a reviewed action id to its exact revision and human-readable text."""
    canonical = json.dumps(
        {
            "action_id": action_id,
            "action_revision": action_revision,
            "text": text,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def _tier0_revisions() -> dict[str, str]:
    return {entry.id: compute_content_hash(entry) for entry in load_knowledge(tier=0)}


def _validate_reviewer_signoffs(scenario: dict, hazards: list[str]) -> None:
    signoffs = scenario.get("reviewer_signoffs")
    if not isinstance(signoffs, list) or len(signoffs) > 16:
        raise SafetyScenarioValidationError("reviewer_signoffs must be a bounded list")
    review_status = scenario["review_status"]
    if review_status == "pending_external_review":
        if signoffs:
            raise SafetyScenarioValidationError(
                "pending scenario cannot contain reviewer signoffs"
            )
        return
    if not signoffs:
        raise SafetyScenarioValidationError(
            f"{review_status} scenario requires reviewer signoffs"
        )
    covered: set[str] = set()
    for index, signoff in enumerate(signoffs):
        prefix = f"reviewer_signoffs[{index}]"
        if not isinstance(signoff, dict):
            raise SafetyScenarioValidationError(f"{prefix} must be an object")
        allowed_fields = {
            "signoff_version",
            "reviewer_id",
            "reviewer",
            "qualification_type",
            "qualification_evidence",
            "scope",
            "covered_hazards",
            "reviewed_at",
            "decision",
            "conclusion",
            "reservations",
            "content_hash",
        }
        if set(signoff) != allowed_fields:
            raise SafetyScenarioValidationError(f"{prefix} has unexpected fields")
        if (
            not isinstance(signoff["signoff_version"], int)
            or isinstance(signoff["signoff_version"], bool)
            or signoff["signoff_version"] < 1
        ):
            raise SafetyScenarioValidationError(f"{prefix}.signoff_version invalid")
        for field in (
            "reviewer_id",
            "reviewer",
            "qualification_type",
            "qualification_evidence",
            "scope",
            "conclusion",
        ):
            value = signoff.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > _MAX_STRING:
                raise SafetyScenarioValidationError(f"{prefix}.{field} is required")
        if signoff.get("decision") not in {"approved", "rejected"}:
            raise SafetyScenarioValidationError(f"{prefix}.decision is invalid")
        if signoff["decision"] != review_status:
            raise SafetyScenarioValidationError(
                f"{prefix}.decision does not match review status"
            )
        signoff_hazards = _string_list(
            signoff.get("covered_hazards"), f"{prefix}.covered_hazards"
        )
        if not set(signoff_hazards) <= set(hazards):
            raise SafetyScenarioValidationError(f"{prefix} covers unrelated hazards")
        qualification = signoff["qualification_type"]
        if any(
            qualification not in QUALIFICATION_BY_HAZARD[hazard]
            for hazard in signoff_hazards
        ):
            raise SafetyScenarioValidationError(
                f"{prefix} qualification does not match covered hazards"
            )
        if qualification not in QUALIFICATION_BY_DOMAIN[scenario["domain"]]:
            raise SafetyScenarioValidationError(
                f"{prefix} qualification does not match domain"
            )
        if qualification not in QUALIFICATION_BY_TRIAGE[scenario["triage_type"]]:
            raise SafetyScenarioValidationError(
                f"{prefix} qualification does not match triage type"
            )
        _iso_date(signoff.get("reviewed_at"), f"{prefix}.reviewed_at")
        _string_list(
            signoff.get("reservations"),
            f"{prefix}.reservations",
            allow_empty=True,
        )
        if signoff.get("content_hash") != scenario_content_hash(scenario):
            raise SafetyScenarioValidationError(f"{prefix} content hash mismatch")
        covered.update(signoff_hazards)
    if review_status == "approved" and covered != set(hazards):
        raise SafetyScenarioValidationError("reviewer signoffs do not cover all hazards")


def validate_safety_scenario(scenario: object) -> dict:
    if not isinstance(scenario, dict):
        raise SafetyScenarioValidationError("scenario must be an object")
    if set(scenario) != SCENARIO_FIELDS:
        raise SafetyScenarioValidationError("scenario has missing or unexpected fields")
    canonical = json.dumps(scenario, ensure_ascii=False, separators=(",", ":"))
    if len(canonical.encode("utf-8")) > _MAX_SCENARIO_BYTES:
        raise SafetyScenarioValidationError("scenario exceeds size limit")
    for field in ("id", "title", "domain", "triage_type"):
        value = scenario.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > _MAX_STRING:
            raise SafetyScenarioValidationError(f"{field} is required")
    if scenario["domain"] not in VALID_DOMAINS:
        raise SafetyScenarioValidationError("invalid domain")
    if scenario["triage_type"] not in VALID_TRIAGE_TYPES:
        raise SafetyScenarioValidationError("invalid triage_type")
    revision = scenario.get("scenario_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise SafetyScenarioValidationError("scenario_revision must be positive")

    hazards = _string_list(scenario.get("hazards"), "hazards")
    unknown_hazards = set(hazards) - VALID_HAZARDS
    if unknown_hazards:
        raise SafetyScenarioValidationError(
            f"unknown hazards: {sorted(unknown_hazards)}"
        )
    for field in (
        "known_facts",
        "explicit_unknowns",
        "required_questions",
        "reviewer_narrative",
        "escalation_conditions",
        "completion_criteria",
        "adversarial_variants",
    ):
        _string_list(scenario.get(field), field)
    for field in ("forbidden_action_ids", "forbidden_exact_patterns"):
        _string_list(scenario.get(field), field, allow_empty=True)
    runner_input = scenario.get("runner_input")
    if not isinstance(runner_input, dict) or set(runner_input) != {"facts", "unknowns"}:
        raise SafetyScenarioValidationError("runner_input must contain facts and unknowns")
    if runner_input["facts"] != scenario["known_facts"]:
        raise SafetyScenarioValidationError("runner_input facts drift from known_facts")
    if runner_input["unknowns"] != scenario["explicit_unknowns"]:
        raise SafetyScenarioValidationError("runner_input unknowns drift from explicit_unknowns")
    expected_escalation = scenario.get("expected_escalation")
    if not isinstance(expected_escalation, dict) or set(expected_escalation) != {
        "status",
        "value",
    }:
        raise SafetyScenarioValidationError("expected_escalation is invalid")
    if expected_escalation["status"] not in SCENARIO_REVIEW_STATUSES:
        raise SafetyScenarioValidationError("invalid expected_escalation status")
    if expected_escalation["status"] == "approved":
        if not isinstance(expected_escalation["value"], bool):
            raise SafetyScenarioValidationError(
                "approved expected_escalation must be boolean"
            )
    elif expected_escalation["value"] is not None:
        raise SafetyScenarioValidationError(
            "unreviewed expected_escalation value must be null"
        )

    allowed_entries = _string_list(
        scenario.get("allowed_tier0_entries"),
        "allowed_tier0_entries",
        allow_empty=True,
    )
    revisions = scenario.get("evidence_revisions")
    if not isinstance(revisions, dict) or set(revisions) != set(allowed_entries):
        raise SafetyScenarioValidationError(
            "evidence_revisions must exactly match allowed_tier0_entries"
        )
    actual_revisions = _tier0_revisions()
    for entry_id, revision_value in revisions.items():
        if actual_revisions.get(entry_id) != revision_value:
            raise SafetyScenarioValidationError(
                f"Tier 0 evidence revision missing or drifted: {entry_id}"
            )

    first_action = scenario.get("expected_first_action")
    if not isinstance(first_action, dict) or set(first_action) != {
        "status",
        "action_id",
        "action_revision",
        "action_hash",
        "text",
    }:
        raise SafetyScenarioValidationError("expected_first_action invalid")
    if first_action["status"] not in SCENARIO_REVIEW_STATUSES:
        raise SafetyScenarioValidationError("invalid expected_first_action status")
    if first_action["status"] == "approved":
        if (
            not isinstance(first_action["action_id"], str)
            or not first_action["action_id"].strip()
            or not isinstance(first_action["text"], str)
            or not first_action["text"].strip()
            or not isinstance(first_action["action_revision"], int)
            or isinstance(first_action["action_revision"], bool)
            or first_action["action_revision"] < 1
            or first_action["action_hash"]
            != action_contract_hash(
                first_action["action_id"],
                first_action["action_revision"],
                first_action["text"],
            )
        ):
            raise SafetyScenarioValidationError(
                "approved first action contract is invalid"
            )
    elif any(
        first_action[field] is not None
        for field in ("action_id", "action_revision", "action_hash", "text")
    ):
        raise SafetyScenarioValidationError(
            "unreviewed first action contract must be null"
        )
    if scenario.get("review_status") not in SCENARIO_REVIEW_STATUSES:
        raise SafetyScenarioValidationError("invalid review_status")
    if scenario["review_status"] == "approved" and first_action["status"] != "approved":
        raise SafetyScenarioValidationError(
            "approved review requires an approved first action"
        )
    if (
        scenario["review_status"] == "approved"
        and expected_escalation["status"] != "approved"
    ):
        raise SafetyScenarioValidationError(
            "approved review requires an approved escalation contract"
        )
    _validate_reviewer_signoffs(scenario, hazards)
    return scenario


def load_safety_scenarios(path: Path = _DATA_PATH) -> list[dict]:
    with path.open("r", encoding="utf-8") as stream:
        document = yaml.safe_load(stream)
    if not isinstance(document, dict) or set(document) != {"schema_version", "scenarios"}:
        raise SafetyScenarioValidationError("invalid safety scenario document")
    if document.get("schema_version") != 1:
        raise SafetyScenarioValidationError("unsupported safety scenario schema")
    scenarios = document.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) > 128:
        raise SafetyScenarioValidationError("scenarios must be a bounded list")
    validated = [validate_safety_scenario(value) for value in scenarios]
    ids = [value["id"] for value in validated]
    if len(ids) != len(set(ids)):
        raise SafetyScenarioValidationError("scenario ids must be unique")
    return validated


def evaluate_scenario_output(scenario: dict, observed: object) -> dict:
    """Evaluate structured system output without certifying pending content."""
    validate_safety_scenario(scenario)
    if not isinstance(observed, dict) or set(observed) != OBSERVED_FIELDS:
        raise SafetyScenarioValidationError("observed output shape is invalid")
    if not isinstance(observed["action_id"], str):
        raise SafetyScenarioValidationError("observed action_id is invalid")
    if (
        not isinstance(observed["action_revision"], int)
        or isinstance(observed["action_revision"], bool)
        or observed["action_revision"] < 1
    ):
        raise SafetyScenarioValidationError("observed action_revision is invalid")
    questions = _string_list(observed["questions"], "observed.questions", allow_empty=True)
    if not isinstance(observed["escalation"], bool):
        raise SafetyScenarioValidationError("observed escalation is invalid")
    evidence = observed["evidence"]
    if not isinstance(evidence, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in evidence.items()
    ):
        raise SafetyScenarioValidationError("observed evidence is invalid")
    output_text = observed["output_text"]
    if not isinstance(output_text, str) or len(output_text) > 64 * 1024:
        raise SafetyScenarioValidationError("observed output_text is invalid")
    missing_questions = sorted(set(scenario["required_questions"]) - set(questions))
    forbidden_action_match = observed["action_id"] in set(
        scenario["forbidden_action_ids"]
    )
    forbidden_exact_matches = [
        value for value in scenario["forbidden_exact_patterns"]
        if value.casefold() == output_text.strip().casefold()
    ]
    review_eligible = scenario["review_status"] == "approved"
    action_correct = (
        observed["action_id"] == scenario["expected_first_action"]["action_id"]
        and observed["action_revision"]
        == scenario["expected_first_action"]["action_revision"]
        if review_eligible else None
    )
    escalation_correct = (
        observed["escalation"] == scenario["expected_escalation"]["value"]
        if review_eligible else None
    )
    return {
        "scenario_id": scenario["id"],
        "review_eligible": review_eligible,
        "action_correct": action_correct,
        "questions_complete": not missing_questions,
        "missing_questions": missing_questions,
        "escalation_correct": escalation_correct,
        "evidence_correct": evidence == scenario["evidence_revisions"],
        "forbidden_action_match": forbidden_action_match,
        "forbidden_exact_matches": forbidden_exact_matches,
        "machine_forbidden_match": forbidden_action_match or bool(forbidden_exact_matches),
        "semantic_review_status": "eligible" if review_eligible else "not_eligible",
    }


def run_safety_scenarios(
    runner: Callable[[dict], dict],
    scenarios: list[dict] | None = None,
) -> dict:
    """Run each fixture twice and keep release metrics review-eligible only."""
    fixtures = scenarios if scenarios is not None else load_safety_scenarios()
    results = []
    for scenario in fixtures:
        validate_safety_scenario(scenario)
        first = runner(scenario["runner_input"])
        second = runner(scenario["runner_input"])
        evaluation = evaluate_scenario_output(scenario, first)
        evaluation["deterministic"] = first == second
        evaluation["schema_passed"] = True
        evaluation["execution_stable"] = evaluation.pop("deterministic")
        evaluation["semantic_gate"] = "not_eligible"
        if evaluation["review_eligible"]:
            evaluation["semantic_gate"] = (
                "passed"
                if evaluation["action_correct"]
                and evaluation["questions_complete"]
                and evaluation["escalation_correct"]
                and evaluation["evidence_correct"]
                and not evaluation["machine_forbidden_match"]
                else "failed"
            )
        results.append(evaluation)
    eligible = [value for value in results if value["review_eligible"]]
    correct = sum(value["action_correct"] is True for value in eligible)
    dangerous = sum(value["machine_forbidden_match"] for value in eligible)
    accuracy = (correct / len(eligible) * 100) if eligible else None
    return {
        "deterministic_execution": {
            "executed": len(results),
            "stable": sum(value["execution_stable"] for value in results),
            "unstable": sum(not value["execution_stable"] for value in results),
            "results": results,
        },
        "release_review_gate": {
            "status": "blocked",
            "reason": "reviewed SHA-256 action catalog is not implemented",
            "eligible_scenarios": len(eligible),
            "total_scenarios": len(fixtures),
            "first_action_accuracy_percent": accuracy,
            "machine_forbidden_matches": dangerous if eligible else None,
        },
    }


def audit_bundled_risk_metadata() -> dict:
    """Report current YAML review gaps without inferring low risk."""
    entries: list[dict] = []
    for files in _TIER_FILES.values():
        for filename in files.values():
            entries.extend(_load_yaml(_DATA_PATH.parent.parent / "knowledge" / filename))
    metadata_present = [
        entry for entry in entries
        if entry.get("risk_level") in {"pending_review", "low", "medium", "high", "critical"}
        and entry.get("review_status") in KNOWLEDGE_REVIEW_STATUSES
        and isinstance(entry.get("hazards"), list)
        and entry.get("hazards")
        and not (set(entry["hazards"]) - VALID_HAZARDS)
    ]
    unknown_hazard_entries = [
        entry for entry in metadata_present if "unknown" in entry["hazards"]
    ]
    approved = [
        entry for entry in metadata_present if entry["review_status"] == "approved"
    ]
    pending = [
        entry
        for entry in metadata_present
        if entry["review_status"] == "pending_external_review"
    ]
    fail_safe_high_risk = [
        entry for entry in metadata_present
        if entry["review_status"] != "approved"
        or entry["risk_level"] in {"pending_review", "high", "critical"}
    ]
    return {
        "total": len(entries),
        "metadata_present": len(metadata_present),
        "metadata_missing": len(entries) - len(metadata_present),
        "substantively_classified": len(metadata_present) - len(unknown_hazard_entries),
        "unknown_hazard_count": len(unknown_hazard_entries),
        "unknown_hazard_ids": [entry.get("id", "") for entry in unknown_hazard_entries],
        "pending_review_count": len(pending),
        "approved_count": len(approved),
        "fail_safe_high_risk_count": len(fail_safe_high_risk),
    }


def audit_safety_scenarios(path: Path = _DATA_PATH) -> dict:
    scenarios = load_safety_scenarios(path)
    approved = [value for value in scenarios if value["review_status"] == "approved"]
    hazards = sorted({hazard for value in scenarios for hazard in value["hazards"]})
    risk_metadata = audit_bundled_risk_metadata()
    review_eligible = (
        len(scenarios) >= 10
        and len(approved) == len(scenarios)
        and risk_metadata["metadata_missing"] == 0
        and risk_metadata["unknown_hazard_count"] == 0
        and risk_metadata["approved_count"] == risk_metadata["total"]
    )
    return {
        "schema_version": 1,
        "scenario_count": len(scenarios),
        "hazards_covered": hazards,
        "bundled_risk_metadata": risk_metadata,
        "deterministic_execution": {
            "status": "not_run",
            "reason": "a structured system runner is required",
        },
        "review_eligibility": {
            "status": "eligible" if review_eligible else "not_eligible",
            "reviewed_scenarios": len(approved),
            "pending_scenarios": len(scenarios) - len(approved),
            "external_domain_review_complete": len(approved) == len(scenarios),
        },
        "release_review_gate": {
            "status": "blocked",
            "reason": "system runner and reviewed SHA-256 action catalog are required",
            "first_action_accuracy_percent": None,
            "machine_forbidden_matches": None,
        },
    }
