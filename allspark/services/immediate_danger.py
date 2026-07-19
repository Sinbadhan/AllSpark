"""Deterministic, review-gated immediate-danger routing for SHA-256."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from allspark.core.i18n import MESSAGES

CATALOG_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "safety" / "action_catalog.yaml"
)
_HASH_PREFIX = "sha256:"
_SUPPORTED_LANGUAGES = {"zh", "en"}
_REVIEW_STATUSES = {"pending_external_review", "approved", "rejected"}
_THREAT_ORDER = (
    "fire_smoke_or_co",
    "severe_bleeding",
    "choking",
    "extreme_heat",
    "extreme_cold",
    "poisoning",
    "medical",
    "other",
    "none",
    "unknown",
)
_THREAT_TYPES = set(_THREAT_ORDER)
_SCENE_STATES = {"yes", "no", "unknown"}
_RESPONSIVE_STATES = {"yes", "no", "unknown"}
_BREATHING_STATES = {"normal", "absent_or_abnormal", "unknown"}
_COMMUNICATION_STATES = {"available", "unavailable", "unknown"}
_AGE_GROUPS = {"infant", "child", "adult", "unknown"}
_COUGH_STATES = {"effective", "ineffective", "unknown"}
_QUESTION_OPTIONS = {
    "threat_type": list(_THREAT_ORDER),
    "scene_safe": ["yes", "no", "unknown"],
    "responsive": ["yes", "no", "unknown"],
    "breathing": ["normal", "absent_or_abnormal", "unknown"],
    "communication": ["available", "unavailable", "unknown"],
    "age_group": ["infant", "child", "adult", "unknown"],
    "effective_cough": ["effective", "ineffective", "unknown"],
}
_ROUTED_ACTION_IDS = {
    "leave-immediate-hazard",
    "move-to-fresh-air",
    "apply-direct-pressure",
    "seek-emergency-response",
    "seek-medical-assessment",
    "keep-distance-seek-local-help",
    "return-to-assessment",
    "begin-heat-cooling",
    "prevent-further-cooling",
    "stop-poison-exposure",
}
_QUALIFICATIONS_BY_ACTION = {
    "leave-immediate-hazard": {
        "environmental_health", "fire_safety", "structural_engineering", "toxicology",
    },
    "move-to-fresh-air": {"emergency_medicine", "environmental_health", "toxicology"},
    "apply-direct-pressure": {"emergency_medicine"},
    "seek-emergency-response": {"emergency_medicine"},
    "seek-medical-assessment": {"emergency_medicine"},
    "keep-distance-seek-local-help": {
        "cross_domain_panel", "environmental_health", "fire_safety",
        "structural_engineering", "toxicology", "violence_prevention",
    },
    "return-to-assessment": {"cross_domain_panel"},
    "begin-heat-cooling": {"emergency_medicine", "environmental_health"},
    "prevent-further-cooling": {"emergency_medicine", "environmental_health"},
    "stop-poison-exposure": {"environmental_health", "toxicology"},
}


class ImmediateDangerValidationError(ValueError):
    """Base error for a violated immediate-danger contract."""

    def __init__(self, field: str, code: str):
        super().__init__(f"{field}: {code}")
        self.field = field
        self.code = code


class ImmediateDangerCatalogError(ImmediateDangerValidationError):
    """Bundled catalog integrity failed; no action may be returned."""


class ImmediateDangerInputError(ImmediateDangerValidationError):
    """A caller supplied a malformed triage fact."""


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return _HASH_PREFIX + hashlib.sha256(encoded).hexdigest()


def _source_hash(source_id: str, source: dict[str, Any]) -> str:
    locator_key = source["locator_key"]
    return _canonical_hash(
        {
            "source_id": source_id,
            **{key: source[key] for key in (
                "organization", "title", "locator", "locator_key", "url",
                "revision", "retrieved_at", "assertion", "captured_assertion",
            )},
            "localized_locator": {
                language: MESSAGES.get(language, {}).get(locator_key, "")
                for language in sorted(_SUPPORTED_LANGUAGES)
            },
        }
    )


def _action_hash(action: dict[str, Any]) -> str:
    text_key = action["text_key"]
    return _canonical_hash(
        {
            key: action[key]
            for key in (
                "action_id",
                "revision",
                "text_key",
                "source_ids",
                "applicable_when",
                "applicable_label_keys",
                "contraindication_keys",
                "escalation_key",
                "review_status",
            )
        }
        | {
            "localized_text": {
                language: {
                    "primary": MESSAGES.get(language, {}).get(text_key, ""),
                    "applicable": [
                        MESSAGES.get(language, {}).get(key, "")
                        for key in action["applicable_label_keys"]
                    ],
                    "contraindications": [
                        MESSAGES.get(language, {}).get(key, "")
                        for key in action["contraindication_keys"]
                    ],
                    "escalation": MESSAGES.get(language, {}).get(
                        action["escalation_key"], ""
                    ),
                }
                for language in sorted(_SUPPORTED_LANGUAGES)
            }
        }
    )


def _catalog_hash(catalog: dict[str, Any]) -> str:
    return _canonical_hash(
        {key: value for key, value in catalog.items() if key != "reviewer_signoffs"}
    )


def _validate_catalog_signoffs(catalog: dict[str, Any]) -> None:
    signoffs = catalog.get("reviewer_signoffs")
    if not isinstance(signoffs, list) or len(signoffs) > 32:
        raise ImmediateDangerCatalogError("reviewer_signoffs", "invalid_shape")
    status = catalog["review_status"]
    if status == "pending_external_review":
        if signoffs:
            raise ImmediateDangerCatalogError("reviewer_signoffs", "pending_must_be_empty")
        return
    if not signoffs:
        raise ImmediateDangerCatalogError("reviewer_signoffs", "required")
    action_ids = {action["action_id"] for action in catalog["actions"]}
    covered: set[str] = set()
    reviewer_ids: set[str] = set()
    expected_hash = _catalog_hash(catalog)
    fields = {
        "signoff_version", "reviewer_id", "reviewer", "qualification_type",
        "qualification_evidence", "scope", "covered_action_ids", "reviewed_at",
        "decision", "conclusion", "reservations", "content_hash",
    }
    for index, signoff in enumerate(signoffs):
        if not isinstance(signoff, dict) or set(signoff) != fields:
            raise ImmediateDangerCatalogError(f"reviewer_signoffs.{index}", "invalid_fields")
        if not isinstance(signoff["signoff_version"], int) or signoff["signoff_version"] < 1:
            raise ImmediateDangerCatalogError(f"reviewer_signoffs.{index}", "invalid_version")
        for field in (
            "reviewer_id", "reviewer", "qualification_type", "qualification_evidence",
            "scope", "conclusion",
        ):
            if not isinstance(signoff[field], str) or not signoff[field].strip():
                raise ImmediateDangerCatalogError(f"reviewer_signoffs.{index}.{field}", "required")
        if signoff["decision"] != status:
            raise ImmediateDangerCatalogError(f"reviewer_signoffs.{index}.decision", "mismatch")
        try:
            reviewed_at = date.fromisoformat(signoff["reviewed_at"])
        except (TypeError, ValueError) as exc:
            raise ImmediateDangerCatalogError(
                f"reviewer_signoffs.{index}.reviewed_at", "invalid_date"
            ) from exc
        if reviewed_at > date.today():
            raise ImmediateDangerCatalogError(
                f"reviewer_signoffs.{index}.reviewed_at", "future_date"
            )
        reviewer_id = signoff["reviewer_id"].strip()
        if reviewer_id in reviewer_ids:
            raise ImmediateDangerCatalogError(
                f"reviewer_signoffs.{index}.reviewer_id", "duplicate_reviewer"
            )
        reviewer_ids.add(reviewer_id)
        action_scope = signoff["covered_action_ids"]
        if (
            not isinstance(action_scope, list)
            or not action_scope
            or not set(action_scope) <= action_ids
        ):
            raise ImmediateDangerCatalogError(
                f"reviewer_signoffs.{index}.covered_action_ids", "invalid_scope"
            )
        qualification = signoff["qualification_type"].strip()
        if any(
            qualification not in _QUALIFICATIONS_BY_ACTION[action_id]
            for action_id in action_scope
        ):
            raise ImmediateDangerCatalogError(
                f"reviewer_signoffs.{index}.qualification_type",
                "action_scope_mismatch",
            )
        if not isinstance(signoff["reservations"], list) or any(
            not isinstance(value, str) or not value.strip()
            for value in signoff["reservations"]
        ):
            raise ImmediateDangerCatalogError(
                f"reviewer_signoffs.{index}.reservations", "invalid_reservations"
            )
        if signoff["content_hash"] != expected_hash:
            raise ImmediateDangerCatalogError(
                f"reviewer_signoffs.{index}.content_hash", "hash_mismatch"
            )
        covered.update(action_scope)
    if status == "approved" and covered != action_ids:
        raise ImmediateDangerCatalogError("reviewer_signoffs", "incomplete_action_coverage")


def _require_string(mapping: dict[str, Any], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ImmediateDangerCatalogError(field, "required_string")
    return value.strip()


def _validate_applicability(value: Any, action_id: str) -> None:
    if not isinstance(value, dict) or set(value) != {"any"}:
        raise ImmediateDangerCatalogError(action_id, "invalid_applicable_when")
    branches = value["any"]
    if not isinstance(branches, list) or not branches:
        raise ImmediateDangerCatalogError(action_id, "invalid_applicable_when")
    allowed_fields = {
        "threat_type": _THREAT_TYPES,
        "scene_safe": _SCENE_STATES,
        "responsive": _RESPONSIVE_STATES,
        "breathing": _BREATHING_STATES,
        "communication": _COMMUNICATION_STATES,
        "age_group": _AGE_GROUPS,
        "effective_cough": _COUGH_STATES,
    }
    for branch in branches:
        if not isinstance(branch, dict) or not branch:
            raise ImmediateDangerCatalogError(action_id, "invalid_applicable_when")
        for field, accepted in branch.items():
            if field not in allowed_fields or not isinstance(accepted, list) or not accepted:
                raise ImmediateDangerCatalogError(action_id, "invalid_applicable_when")
            if any(not isinstance(item, str) or item not in allowed_fields[field] for item in accepted):
                raise ImmediateDangerCatalogError(action_id, "invalid_applicable_when")


def action_applies(action: dict[str, Any], facts: dict[str, str]) -> bool:
    """Evaluate the catalog's OR-of-ANDs applicability predicate."""
    return any(
        all(facts.get(field) in accepted for field, accepted in branch.items())
        for branch in action["applicable_when"]["any"]
    )


@lru_cache(maxsize=1)
def load_action_catalog() -> dict[str, Any]:
    try:
        with CATALOG_PATH.open(encoding="utf-8") as stream:
            document = yaml.safe_load(stream)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ImmediateDangerCatalogError("catalog", "load_failed") from exc
    if not isinstance(document, dict):
        raise ImmediateDangerCatalogError("catalog", "object_required")
    if document.get("schema_version") != 1 or document.get("catalog_revision") != 1:
        raise ImmediateDangerCatalogError("catalog", "unsupported_version")
    review_status = document.get("review_status")
    if review_status not in _REVIEW_STATUSES:
        raise ImmediateDangerCatalogError("review_status", "invalid_status")
    if document.get("release_eligible") is not (review_status == "approved"):
        raise ImmediateDangerCatalogError("release_eligible", "status_mismatch")
    sources = document.get("sources")
    actions = document.get("actions")
    if not isinstance(sources, dict) or not isinstance(actions, list) or not actions:
        raise ImmediateDangerCatalogError("catalog", "sources_actions_required")
    for source_id, source in sources.items():
        if not isinstance(source_id, str) or not isinstance(source, dict):
            raise ImmediateDangerCatalogError("sources", "invalid_shape")
        for field in (
            "organization", "title", "locator", "locator_key", "url", "revision",
            "retrieved_at", "assertion", "captured_assertion",
        ):
            _require_string(source, field)
        try:
            retrieved_at = date.fromisoformat(source["retrieved_at"])
        except ValueError as exc:
            raise ImmediateDangerCatalogError(
                f"sources.{source_id}.retrieved_at", "invalid_date"
            ) from exc
        if retrieved_at > date.today():
            raise ImmediateDangerCatalogError(
                f"sources.{source_id}.retrieved_at", "future_date"
            )
        locator_key = source["locator_key"]
        if any(not MESSAGES.get(lang, {}).get(locator_key) for lang in _SUPPORTED_LANGUAGES):
            raise ImmediateDangerCatalogError(locator_key, "missing_translation")
        if source.get("content_hash") != _source_hash(source_id, source):
            raise ImmediateDangerCatalogError(
                f"sources.{source_id}.content_hash", "hash_mismatch"
            )
    seen: set[str] = set()
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise ImmediateDangerCatalogError(f"actions.{index}", "object_required")
        action_id = _require_string(action, "action_id")
        if action_id in seen:
            raise ImmediateDangerCatalogError("actions", "duplicate_action_id")
        seen.add(action_id)
        if action.get("revision") != 1 or action.get("review_status") != review_status:
            raise ImmediateDangerCatalogError(action_id, "invalid_review_contract")
        text_key = _require_string(action, "text_key")
        if any(not MESSAGES.get(lang, {}).get(text_key) for lang in _SUPPORTED_LANGUAGES):
            raise ImmediateDangerCatalogError(text_key, "missing_translation")
        source_ids = action.get("source_ids")
        if not isinstance(source_ids, list) or any(
            not isinstance(item, str) or item not in sources for item in source_ids
        ):
            raise ImmediateDangerCatalogError(action_id, "invalid_source_ids")
        _validate_applicability(action.get("applicable_when"), action_id)
        for field in ("applicable_label_keys", "contraindication_keys"):
            values = action.get(field)
            if not isinstance(values, list) or not all(
                isinstance(item, str) and item.strip() for item in values
            ):
                raise ImmediateDangerCatalogError(action_id, f"invalid_{field}")
            if any(
                not MESSAGES.get(lang, {}).get(key)
                for key in values
                for lang in _SUPPORTED_LANGUAGES
            ):
                raise ImmediateDangerCatalogError(action_id, f"missing_{field}")
        if len(action["applicable_when"]["any"]) != len(
            action["applicable_label_keys"]
        ):
            raise ImmediateDangerCatalogError(
                action_id, "applicability_label_count_mismatch"
            )
        escalation_key = _require_string(action, "escalation_key")
        if any(
            not MESSAGES.get(lang, {}).get(escalation_key)
            for lang in _SUPPORTED_LANGUAGES
        ):
            raise ImmediateDangerCatalogError(action_id, "missing_escalation")
        if action.get("content_hash") != _action_hash(action):
            raise ImmediateDangerCatalogError(
                f"actions.{action_id}.content_hash", "hash_mismatch"
            )
    if seen != _ROUTED_ACTION_IDS:
        raise ImmediateDangerCatalogError("actions", "routed_action_set_mismatch")
    _validate_catalog_signoffs(document)
    return document


def _value(payload: dict[str, Any], field: str, allowed: set[str]) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or value not in allowed:
        raise ImmediateDangerInputError(field, "invalid_choice")
    return value


def _question(field: str) -> dict[str, Any]:
    catalog = load_action_catalog()
    return {
        "status": "needs_fact",
        "question": {"field": field, "options": _QUESTION_OPTIONS[field]},
        "release_eligible": catalog["release_eligible"],
        "review_status": catalog["review_status"],
    }


def _action(
    action_id: str,
    language: str,
    communication: str | None,
    facts: dict[str, str],
) -> dict[str, Any]:
    catalog = load_action_catalog()
    action = next(
        (item for item in catalog["actions"] if item["action_id"] == action_id), None
    )
    if action is None:
        raise ImmediateDangerCatalogError(action_id, "routed_action_missing")
    if not action_applies(action, facts):
        raise ImmediateDangerCatalogError(action_id, "route_not_applicable")
    sources = []
    for source_id in action["source_ids"]:
        source = catalog["sources"][source_id]
        sources.append(
            {
                "source_id": source_id,
                "organization": source["organization"],
                "title": source["title"],
                "locator": MESSAGES[language][source["locator_key"]],
                "url": source["url"],
                "revision": source["revision"],
                "content_hash": source["content_hash"],
            }
        )
    return {
        "status": "action",
        "action": {
            "action_id": action["action_id"],
            "revision": action["revision"],
            "content_hash": action["content_hash"],
            "text": MESSAGES[language][action["text_key"]],
            "sources": sources,
            "applicable_when": action["applicable_when"],
            "applicable_when_labels": [
                MESSAGES[language][key] for key in action["applicable_label_keys"]
            ],
            "contraindications": [
                MESSAGES[language][key] for key in action["contraindication_keys"]
            ],
            "escalation": MESSAGES[language][action["escalation_key"]],
            "communication_status": communication or "unknown",
            "review_status": action["review_status"],
        },
        "follow_up_question": (
            {"field": "communication", "options": _QUESTION_OPTIONS["communication"]}
            if communication is None and action_id != "return-to-assessment"
            else None
        ),
        "catalog": {
            "catalog_id": catalog["catalog_id"],
            "revision": catalog["catalog_revision"],
            "review_status": catalog["review_status"],
        },
        "release_eligible": catalog["release_eligible"],
    }


def assess_immediate_danger(
    payload: Any, language: str = "en"
) -> dict[str, Any]:
    """Return the next required fact or one fixed first action without writes."""
    if not isinstance(payload, dict):
        raise ImmediateDangerInputError("payload", "object_required")
    if not isinstance(language, str) or language not in _SUPPORTED_LANGUAGES:
        raise ImmediateDangerInputError("language", "invalid_choice")
    threat = _value(payload, "threat_type", _THREAT_TYPES)
    scene = _value(payload, "scene_safe", _SCENE_STATES)
    responsive = _value(payload, "responsive", _RESPONSIVE_STATES)
    breathing = _value(payload, "breathing", _BREATHING_STATES)
    communication = _value(payload, "communication", _COMMUNICATION_STATES)
    age_group = _value(payload, "age_group", _AGE_GROUPS)
    effective_cough = _value(payload, "effective_cough", _COUGH_STATES)
    if threat is None:
        return _question("threat_type")
    if threat == "none":
        if scene in {"no", "unknown"}:
            return _action("leave-immediate-hazard", language, communication, payload)
        return _action("return-to-assessment", language, communication, payload)
    if scene is None:
        return _question("scene_safe")
    if scene != "yes":
        return _action("leave-immediate-hazard", language, communication, payload)
    if threat == "fire_smoke_or_co":
        return _action("move-to-fresh-air", language, communication, payload)
    if threat == "severe_bleeding":
        return _action("apply-direct-pressure", language, communication, payload)
    if threat == "extreme_heat":
        return _action("begin-heat-cooling", language, communication, payload)
    if threat == "extreme_cold":
        return _action("prevent-further-cooling", language, communication, payload)
    if threat == "poisoning":
        return _action("stop-poison-exposure", language, communication, payload)
    if threat in {"other", "unknown"}:
        return _action("keep-distance-seek-local-help", language, communication, payload)
    if responsive is None:
        return _question("responsive")
    if breathing is None:
        return _question("breathing")
    if breathing == "absent_or_abnormal":
        return _action("seek-emergency-response", language, communication, payload)
    if threat == "choking":
        if breathing != "normal":
            return _action("seek-emergency-response", language, communication, payload)
        if responsive != "yes":
            return _action("seek-emergency-response", language, communication, payload)
        if age_group is None:
            return _question("age_group")
        if effective_cough is None:
            return _question("effective_cough")
        if effective_cough != "effective":
            return _action("seek-emergency-response", language, communication, payload)
        return _action("seek-medical-assessment", language, communication, payload)
    if responsive == "yes":
        return _action("seek-medical-assessment", language, communication, payload)
    return _action("seek-emergency-response", language, communication, payload)


def action_catalog_audit() -> dict[str, Any]:
    catalog = load_action_catalog()
    return {
        "catalog_id": catalog["catalog_id"],
        "revision": catalog["catalog_revision"],
        "action_count": len(catalog["actions"]),
        "review_status": catalog["review_status"],
        "release_eligible": catalog["release_eligible"],
    }
