import hashlib
import json
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ResourceType(Enum):
    POWER = "power"
    WATER = "water"
    FOOD = "food"
    FIRE = "fire"
    STORAGE = "storage"


RESOURCE_UNITS = {
    ResourceType.POWER: "Wh",
    ResourceType.WATER: "L",
    ResourceType.FOOD: "kcal",
    ResourceType.FIRE: "uses",
    ResourceType.STORAGE: "GB",
}


class OperatingMode(Enum):
    PROACTIVE = "proactive"
    STANDARD = "standard"
    ECONOMY = "economy"
    HIBERNATION = "hibernation"
    RECOVERY = "recovery"


class SurvivalPhase(Enum):
    IMMEDIATE = 0
    SHORT_TERM = 1
    MID_TERM = 2
    QUALITY = 3
    RENAISSANCE = 4


class PersonalityMode(Enum):
    CRISIS = "crisis"
    STABLE = "stable"
    COMPANION = "companion"
    MULTIPLAYER = "multiplayer"
    RENAISSANCE = "renaissance"


class GovernanceRole(Enum):
    COMMANDER = "commander"
    SPECIALIST = "specialist"
    EXECUTOR = "executor"
    OBSERVER = "observer"


class SpecialistDomain(Enum):
    MEDICAL = "medical"
    ENGINEERING = "engineering"
    AGRICULTURE = "agriculture"
    DEFENSE = "defense"
    LOGISTICS = "logistics"
    COMMUNICATION = "communication"
    EDUCATION = "education"


class ConflictStatus(Enum):
    OPEN = "open"
    MEDIATING = "mediating"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class TradeStatus(Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskPriority(Enum):
    URGENT = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3


class ResetLevel(Enum):
    ASSESSMENT = 1     # L1: 重置评估
    ARCHIVE = 2        # L2: 重置档案
    FACTORY = 3        # L3: 重置出厂


class GoalPriority(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class GoalStatus(Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    PAUSED = "paused"


class GoalType(Enum):
    AUTO = "auto"
    MANUAL = "manual"


class GoalSource(Enum):
    ASSESSMENT = "assessment"
    SURVIVOR = "survivor"
    TRADE = "trade"
    EXPERIENCE = "experience"


class GoalCategory(Enum):
    SURVIVAL = "survival"
    QUALITY = "quality"
    EXPLORATION = "exploration"
    COMMUNITY = "community"
    CIVILIZATION = "civilization"


class TimelineEventType(Enum):
    GOAL_COMPLETED = "goal_completed"
    RESOURCE_CHANGE = "resource_change"
    MEMBER_JOINED = "member_joined"
    KNOWLEDGE_ACQUIRED = "knowledge_acquired"
    MILESTONE = "milestone"
    DIARY_ENTRY = "diary_entry"
    SYSTEM_EVENT = "system_event"


class DiaryEmotion(Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


@dataclass
class Resource:
    type: ResourceType
    current_amount: float
    unit: str
    daily_consumption: float = 0.0
    daily_intake: float = 0.0
    rate_basis: str = "unknown"
    estimated_remaining_hours: float = 0.0
    last_updated: str = ""
    amount_known: bool = False
    consumption_known: bool = False
    intake_known: bool = False
    source: str = "migration"
    people_count: int = 1
    people_count_known: bool = False
    as_of: str = ""
    capacity: float = 0.0
    capacity_known: bool = False


@dataclass
class SurvivorState:
    health_status: str = "unknown"
    skills: list[str] = field(default_factory=list)
    psychological_state: str = "unknown"
    injuries: list[str] = field(default_factory=list)


class TaskType(Enum):
    MAIN = "main"
    SIDE = "side"


@dataclass
class Task:
    id: str
    phase: int
    priority: int
    title: str
    description: str = ""
    status: str = "pending"
    task_type: str = "main"
    created_at: str = ""
    updated_at: str = ""


@dataclass
class PlanAction:
    """A deterministic 24-hour plan action, separate from execution Tasks."""

    id: str
    domain: str
    priority: int
    title_key: str
    why_now: str
    evidence: list[dict] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)
    risk: str = ""
    done_when: str = ""
    reassess_at: str = "PT4H"
    status: str = "proposed"
    order: int = 0


@dataclass
class SurvivalPlan:
    """Persisted Assess→Decide output for the next 24 hours."""

    id: str
    assessment_hash: str
    fingerprint: str
    phase: int | None
    phase_status: str
    missing_fields: list[str] = field(default_factory=list)
    stale_fields: list[str] = field(default_factory=list)
    actions: list[PlanAction] = field(default_factory=list)
    accepted_action_id: str = ""
    status: str = "draft"
    horizon_hours: int = 24
    created_at: str = ""
    updated_at: str = ""


@dataclass
class KnowledgeEntry:
    id: str
    category: str
    subcategory: str
    priority: int
    title: str
    summary: str
    steps: list[str] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    verification: str = "unverified"
    source: str = "pre_collapse"
    version: int = 1
    language: str = "zh"
    # SHA-148: auditable expert signoff. Empty/0 by default = "no formal
    # signoff". ``expert_verified`` must never be assigned without a populated
    # reviewer + signoff_version whose content_hash still matches the entry
    # content (see is_signed_off / compute_content_hash).
    reviewer: str = ""
    qualification: str = ""
    review_date: str = ""
    citation: str = ""
    content_hash: str = ""
    signoff_version: int = 0
    # SHA-240: evidence and safety boundaries travel with the claim, but only
    # locally verified evidence may raise the derived verification level.
    references: list[dict] = field(default_factory=list)
    field_records: list[dict] = field(default_factory=list)
    applicable_when: list[str] = field(default_factory=list)
    contraindications: list[str] = field(default_factory=list)
    verification_claim: str = ""
    source_claim: str = ""
    source_content_hash: str = ""
    review_claim: dict = field(default_factory=dict)
    # SHA-241: explicit safety classification. Empty values only exist for
    # legacy transport compatibility and are treated fail-closed as high risk.
    risk_level: str = ""
    hazards: list[str] = field(default_factory=list)
    review_status: str = ""
    risk_reviews: list[dict] = field(default_factory=list)
    risk_review_claims: list[dict] = field(default_factory=list)

    def is_signed_off(self) -> bool:
        """True only when a named expert has signed off AND the content is
        unchanged since signing (SHA-148). An entry without a reviewer, or one
        whose content drifted from the pinned hash, is NOT signed off and must
        not be labeled ``expert_verified``."""
        return (
            bool(self.reviewer)
            and bool(self.qualification)
            and _valid_iso_datetime(self.review_date)
            and _non_url_locator(self.citation)
            and self.signoff_version > 0
            and bool(self.content_hash)
            and self.content_hash == compute_content_hash(self)
        )


def compute_content_hash(entry: "KnowledgeEntry") -> str:
    """SHA-256 of an entry's content fields (SHA-148 signoff pin).

    Signoff fields are excluded so signing does not change the hash. Editing
    any content field invalidates a signoff pinned to the old hash.
    """
    parts = [
        entry.id, entry.category, entry.subcategory, str(entry.priority),
        entry.title, entry.summary,
        json.dumps(entry.steps, ensure_ascii=False, sort_keys=True),
        json.dumps(entry.prerequisites, ensure_ascii=False, sort_keys=True),
        json.dumps(entry.warnings, ensure_ascii=False, sort_keys=True),
    ]
    # Preserve hashes created before SHA-240 when no evidence/boundary data is
    # present. Once any of these fields exists, every one participates in the
    # pin so changing evidence or its safety boundary invalidates signoff.
    evidence_fields = {
        "references": entry.references,
        "field_records": entry.field_records,
        "applicable_when": entry.applicable_when,
        "contraindications": entry.contraindications,
        "review_claim": entry.review_claim,
    }
    if any(evidence_fields.values()):
        parts.append(json.dumps(evidence_fields, ensure_ascii=False, sort_keys=True))
    risk_fields = {
        "risk_level": entry.risk_level,
        "hazards": entry.hazards,
    }
    if any(risk_fields.values()):
        parts.append(json.dumps(risk_fields, ensure_ascii=False, sort_keys=True))
    return "sha256:" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def compute_source_content_hash(entry: "KnowledgeEntry") -> str:
    """Pin the repository-supplied version before local evidence is merged."""
    payload = {
        "content_hash": compute_content_hash(entry),
        "version": entry.version,
        "language": entry.language,
        "source": entry.source,
    }
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _non_url_locator(value) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and not value.strip().lower().startswith(("http://", "https://"))
    )


def _valid_iso_datetime(value) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def canonical_source_id(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


_EVIDENCE_ITEMS_MAX = 32
_CONDITIONS_MAX = 16
_TEXT_MAX = 2048
_EVIDENCE_BYTES_MAX = 131_072
_REFERENCE_FIELDS = {
    "source_id", "title", "organization", "locator", "url",
    "local_status", "verified_by", "verified_at",
}
_FIELD_RECORD_FIELDS = {
    "record_id", "source_id", "conditions", "outcome", "recorded_at",
    "locator", "local_status", "verified_by", "verified_at",
}
_REVIEW_CLAIM_FIELDS = {
    "reviewer", "qualification", "review_date", "citation", "content_hash",
    "signoff_version", "local_status",
}


class KnowledgeValidationError(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class KnowledgeEvidenceValidationError(KnowledgeValidationError):
    pass


def validate_knowledge_entry_schema(entry: "KnowledgeEntry") -> None:
    """Shared SKF/Spark base-content boundary before trust evaluation."""
    scalar_limits = {
        "id": 128, "category": 64, "subcategory": 64, "title": 1024,
        "summary": 16384, "verification": 32, "source": 64,
        "verification_claim": 32, "source_claim": 64, "language": 8,
    }
    required = {"id", "category", "title", "summary"}
    for field_name, limit in scalar_limits.items():
        value = getattr(entry, field_name)
        if not isinstance(value, str) or len(value) > limit:
            raise KnowledgeValidationError(f"knowledge_{field_name}_invalid")
        if field_name in required and not value.strip():
            raise KnowledgeValidationError(f"knowledge_{field_name}_required")
    if entry.verification not in KNOWLEDGE_VERIFICATION_LEVELS:
        raise KnowledgeValidationError("knowledge_verification_invalid")
    if entry.language not in {"zh", "en"}:
        raise KnowledgeValidationError("knowledge_language_invalid")
    risk_values_present = bool(
        entry.risk_level
        or entry.hazards
        or entry.review_status
        or entry.risk_reviews
        or entry.risk_review_claims
    )
    if risk_values_present:
        if entry.risk_level not in KNOWLEDGE_RISK_LEVELS:
            raise KnowledgeValidationError("knowledge_risk_level_invalid")
        if entry.review_status not in KNOWLEDGE_RISK_REVIEW_STATUSES:
            raise KnowledgeValidationError("knowledge_review_status_invalid")
        if (
            not isinstance(entry.hazards, list)
            or not entry.hazards
            or len(entry.hazards) > 16
            or len(entry.hazards) != len(set(entry.hazards))
            or any(
                not isinstance(hazard, str) or hazard not in KNOWLEDGE_HAZARDS
                for hazard in entry.hazards
            )
        ):
            raise KnowledgeValidationError("knowledge_hazards_invalid")
        covered = _validate_risk_reviews(entry, entry.risk_reviews, local=True)
        _validate_risk_reviews(entry, entry.risk_review_claims, local=False)
        if entry.review_status == "approved" and covered != set(entry.hazards):
            raise KnowledgeValidationError("knowledge_approved_risk_review_incomplete")
        if entry.review_status == "rejected" and not entry.risk_reviews:
            raise KnowledgeValidationError("knowledge_rejected_risk_review_required")
        if entry.review_status == "pending_external_review" and entry.risk_reviews:
            raise KnowledgeValidationError("knowledge_pending_local_risk_review_forbidden")
    if any(char in entry.id for char in '<>"\'`&') or any(
        ord(char) < 32 for char in entry.id
    ):
        raise KnowledgeValidationError("knowledge_id_unsafe")
    if (
        not isinstance(entry.priority, int)
        or isinstance(entry.priority, bool)
        or entry.priority not in (0, 1, 2, 3)
    ):
        raise KnowledgeValidationError("knowledge_priority_invalid")
    if (
        not isinstance(entry.version, int)
        or isinstance(entry.version, bool)
        or not 0 <= entry.version <= 1_000_000
    ):
        raise KnowledgeValidationError("knowledge_version_invalid")
    for field_name in ("steps", "prerequisites", "warnings"):
        values = getattr(entry, field_name)
        if not isinstance(values, list) or len(values) > _KNOWLEDGE_CONTENT_LIST_MAX:
            raise KnowledgeValidationError(f"knowledge_{field_name}_invalid_count")
        for value in values:
            if not isinstance(value, str) or len(value) > _KNOWLEDGE_CONTENT_TEXT_MAX:
                raise KnowledgeValidationError(f"knowledge_{field_name}_invalid_item")


_KNOWLEDGE_CONTENT_LIST_MAX = 128
_KNOWLEDGE_CONTENT_TEXT_MAX = 4096
KNOWLEDGE_VERIFICATION_LEVELS = {
    "expert_verified", "cross_ref", "field_tested", "partially_verified",
    "unverified", "conflict",
}
KNOWLEDGE_RISK_LEVELS = {"pending_review", "low", "medium", "high", "critical"}
KNOWLEDGE_RISK_REVIEW_STATUSES = {
    "pending_external_review",
    "approved",
    "rejected",
}
KNOWLEDGE_HAZARDS = {
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
RISK_QUALIFICATIONS_BY_HAZARD = {
    "biological": {"biology", "environmental_health", "emergency_medicine"},
    "electrical": {"electrical_engineering"},
    "environmental": {"environmental_health", "survival_operations"},
    "explosion": {"fire_safety", "mechanical_engineering"},
    "fire": {"fire_safety"},
    "mechanical": {"mechanical_engineering"},
    "medical": {"emergency_medicine"},
    "structural": {"structural_engineering"},
    "toxic": {"toxicology", "environmental_health"},
    "unknown": {"cross_domain_panel"},
    "violence": {"violence_prevention"},
}
_RISK_REVIEW_FIELDS = {
    "signoff_version",
    "reviewer_id",
    "reviewer",
    "qualification_type",
    "qualification_evidence",
    "covered_hazards",
    "reviewed_at",
    "conclusion",
    "reservations",
    "classification_hash",
}


def compute_risk_classification_hash(entry: "KnowledgeEntry") -> str:
    """Pin knowledge semantics plus risk level/hazards, excluding the review."""
    return compute_content_hash(entry)


def normalize_knowledge_risk_metadata(entry: "KnowledgeEntry") -> None:
    """Convert only a wholly absent legacy classification to fail-closed state."""
    if not any(
        (
            entry.risk_level,
            entry.hazards,
            entry.review_status,
            entry.risk_reviews,
            entry.risk_review_claims,
        )
    ):
        entry.risk_level = "pending_review"
        entry.hazards = ["unknown"]
        entry.review_status = "pending_external_review"


def _validate_risk_reviews(
    entry: "KnowledgeEntry", reviews: object, *, local: bool
) -> set[str]:
    if not isinstance(reviews, list) or len(reviews) > 16:
        raise KnowledgeValidationError("knowledge_risk_reviews_invalid")
    all_covered: set[str] = set()
    for review in reviews:
        if not isinstance(review, dict) or set(review) != _RISK_REVIEW_FIELDS:
            raise KnowledgeValidationError("knowledge_risk_review_invalid_fields")
        version = review.get("signoff_version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise KnowledgeValidationError("knowledge_risk_review_invalid_version")
        for field_name in (
            "reviewer_id",
            "reviewer",
            "qualification_type",
            "qualification_evidence",
            "conclusion",
            "classification_hash",
        ):
            value = review.get(field_name)
            if not isinstance(value, str) or not value.strip() or len(value) > 4096:
                raise KnowledgeValidationError(
                    f"knowledge_risk_review_{field_name}_invalid"
                )
        if not _valid_iso_datetime(review.get("reviewed_at")):
            raise KnowledgeValidationError("knowledge_risk_review_reviewed_at_invalid")
        covered = review.get("covered_hazards")
        if (
            not isinstance(covered, list)
            or not covered
            or len(covered) != len(set(covered))
            or not set(covered) <= set(entry.hazards)
        ):
            raise KnowledgeValidationError("knowledge_risk_review_hazards_invalid")
        reservations = review.get("reservations")
        if (
            not isinstance(reservations, list)
            or len(reservations) > 32
            or any(
                not isinstance(value, str) or not value.strip() or len(value) > 4096
                for value in reservations
            )
        ):
            raise KnowledgeValidationError("knowledge_risk_review_reservations_invalid")
        qualification = review["qualification_type"]
        if any(
            qualification not in RISK_QUALIFICATIONS_BY_HAZARD[hazard]
            for hazard in covered
        ):
            raise KnowledgeValidationError(
                "knowledge_risk_review_qualification_invalid"
            )
        conclusion = review["conclusion"].strip().casefold()
        if conclusion not in {"approved", "rejected"}:
            raise KnowledgeValidationError("knowledge_risk_review_conclusion_invalid")
        if local and conclusion != entry.review_status:
            raise KnowledgeValidationError("knowledge_risk_review_decision_mismatch")
        classification_hash = review["classification_hash"]
        if local and classification_hash != compute_risk_classification_hash(entry):
            raise KnowledgeValidationError("knowledge_risk_review_hash_mismatch")
        if not local and (
            not classification_hash.startswith("sha256:")
            or len(classification_hash) != 71
            or any(value not in "0123456789abcdef" for value in classification_hash[7:])
        ):
            raise KnowledgeValidationError("knowledge_risk_review_hash_invalid")
        all_covered.update(covered)
    return all_covered


def _validate_text(value, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise KnowledgeEvidenceValidationError(f"{field}_must_be_non_empty_text")
    if len(value) > _TEXT_MAX:
        raise KnowledgeEvidenceValidationError(f"{field}_too_long")


def _validate_string_list(values, field: str, limit: int) -> None:
    if not isinstance(values, list):
        raise KnowledgeEvidenceValidationError(f"{field}_must_be_list")
    if len(values) > limit:
        raise KnowledgeEvidenceValidationError(f"{field}_too_many_items")
    for value in values:
        _validate_text(value, field)


def validate_knowledge_evidence(entry: "KnowledgeEntry") -> None:
    """Reject an unsafe evidence envelope; never delete its safety boundary."""
    try:
        raw = json.dumps(
            [
                entry.references, entry.field_records, entry.applicable_when,
                entry.contraindications, entry.review_claim,
            ],
            ensure_ascii=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise KnowledgeEvidenceValidationError("evidence_not_json_serializable") from exc
    if len(raw) > _EVIDENCE_BYTES_MAX:
        raise KnowledgeEvidenceValidationError("evidence_payload_too_large")
    if not isinstance(entry.references, list) or len(entry.references) > _EVIDENCE_ITEMS_MAX:
        raise KnowledgeEvidenceValidationError("references_invalid_count")
    for reference in entry.references:
        if not isinstance(reference, dict) or not set(reference).issubset(_REFERENCE_FIELDS):
            raise KnowledgeEvidenceValidationError("reference_invalid_shape")
        for key, value in reference.items():
            _validate_text(value, f"reference_{key}")
        for required in ("source_id", "title", "locator"):
            if required not in reference:
                raise KnowledgeEvidenceValidationError(f"reference_missing_{required}")
        if not _non_url_locator(reference["locator"]):
            raise KnowledgeEvidenceValidationError("reference_locator_not_precise")
        if reference.get("local_status") == "verified":
            for required in ("verified_by", "verified_at"):
                if required not in reference:
                    raise KnowledgeEvidenceValidationError(
                        f"verified_reference_missing_{required}"
                    )
            if not _valid_iso_datetime(reference["verified_at"]):
                raise KnowledgeEvidenceValidationError("verified_reference_invalid_date")
    if not isinstance(entry.field_records, list) or len(entry.field_records) > _EVIDENCE_ITEMS_MAX:
        raise KnowledgeEvidenceValidationError("field_records_invalid_count")
    for record in entry.field_records:
        if not isinstance(record, dict) or not set(record).issubset(_FIELD_RECORD_FIELDS):
            raise KnowledgeEvidenceValidationError("field_record_invalid_shape")
        for key, value in record.items():
            if key == "conditions":
                _validate_string_list(value, "conditions", _CONDITIONS_MAX)
            else:
                _validate_text(value, f"field_record_{key}")
        for required in (
            "record_id", "source_id", "conditions", "outcome", "recorded_at", "locator",
        ):
            if required not in record:
                raise KnowledgeEvidenceValidationError(f"field_record_missing_{required}")
        if not _valid_iso_datetime(record["recorded_at"]):
            raise KnowledgeEvidenceValidationError("field_record_invalid_date")
        if not _non_url_locator(record["locator"]):
            raise KnowledgeEvidenceValidationError("field_record_locator_not_precise")
        if record.get("local_status") == "verified":
            for required in ("verified_by", "verified_at"):
                if required not in record:
                    raise KnowledgeEvidenceValidationError(
                        f"verified_field_record_missing_{required}"
                    )
            if not _valid_iso_datetime(record["verified_at"]):
                raise KnowledgeEvidenceValidationError("verified_field_record_invalid_date")
    _validate_string_list(entry.applicable_when, "applicable_when", _EVIDENCE_ITEMS_MAX)
    _validate_string_list(entry.contraindications, "contraindications", _EVIDENCE_ITEMS_MAX)
    if not isinstance(entry.review_claim, dict) or not set(entry.review_claim).issubset(
        _REVIEW_CLAIM_FIELDS
    ):
        raise KnowledgeEvidenceValidationError("review_claim_invalid_shape")
    for key, value in entry.review_claim.items():
        if key == "signoff_version":
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 1_000_000:
                raise KnowledgeEvidenceValidationError("review_claim_invalid_version")
        else:
            _validate_text(value, f"review_claim_{key}")
    if entry.review_claim:
        for required in (
            "reviewer", "qualification", "review_date", "citation", "content_hash",
            "signoff_version",
        ):
            if required not in entry.review_claim:
                raise KnowledgeEvidenceValidationError(f"review_claim_missing_{required}")
        if not _valid_iso_datetime(entry.review_claim["review_date"]):
            raise KnowledgeEvidenceValidationError("review_claim_invalid_date")
        if not _non_url_locator(entry.review_claim["citation"]):
            raise KnowledgeEvidenceValidationError("review_claim_citation_not_precise")
        if entry.review_claim["signoff_version"] <= 0:
            raise KnowledgeEvidenceValidationError("review_claim_invalid_version")


def _normalize_strings(values, *, limit: int = _EVIDENCE_ITEMS_MAX) -> list[str]:
    del limit
    return [value.strip() for value in values]


def _normalize_dicts(values, allowed: set[str], *, field_record: bool) -> list[dict]:
    result = []
    for value in values:
        normalized: dict[str, object] = {}
        for key in allowed:
            raw = value.get(key)
            if key == "conditions" and field_record:
                normalized[key] = _normalize_strings(raw, limit=_CONDITIONS_MAX)
            elif isinstance(raw, str):
                normalized[key] = raw.strip()
        result.append(normalized)
    return result


def normalize_knowledge_evidence(entry: "KnowledgeEntry") -> None:
    """Bound and normalize persisted evidence supplied by any ingress."""
    validate_knowledge_evidence(entry)
    entry.references = _normalize_dicts(
        entry.references, _REFERENCE_FIELDS, field_record=False
    )
    entry.field_records = _normalize_dicts(
        entry.field_records, _FIELD_RECORD_FIELDS, field_record=True
    )
    entry.applicable_when = _normalize_strings(entry.applicable_when)
    entry.contraindications = _normalize_strings(entry.contraindications)
    if isinstance(entry.review_claim, dict):
        normalized_review: dict[str, object] = {}
        for key in _REVIEW_CLAIM_FIELDS:
            raw = entry.review_claim.get(key)
            if key == "signoff_version" and isinstance(raw, int) and not isinstance(raw, bool):
                normalized_review[key] = raw
            elif isinstance(raw, str):
                normalized_review[key] = raw.strip()
        entry.review_claim = normalized_review
    else:
        entry.review_claim = {}


def verified_references(entry: "KnowledgeEntry") -> list[dict]:
    """Return locally verified, locatable references, deduplicated by source."""
    result = []
    seen = set()
    for reference in entry.references:
        if not isinstance(reference, dict):
            continue
        source_id = reference.get("source_id")
        title = reference.get("title")
        if (
            reference.get("local_status") != "verified"
            or not isinstance(source_id, str)
            or not source_id.strip()
            or canonical_source_id(source_id) in seen
            or not isinstance(title, str)
            or not title.strip()
            or not _non_url_locator(reference.get("locator"))
            or not isinstance(reference.get("verified_by"), str)
            or not reference["verified_by"].strip()
            or not _valid_iso_datetime(reference.get("verified_at"))
        ):
            continue
        seen.add(canonical_source_id(source_id))
        result.append(reference)
    return result


def verified_field_records(entry: "KnowledgeEntry") -> list[dict]:
    """Return complete field records accepted by the local controlled workflow."""
    result = []
    for record in entry.field_records:
        if not isinstance(record, dict):
            continue
        conditions = record.get("conditions")
        required_strings = (
            "record_id", "source_id", "outcome", "recorded_at",
            "verified_by", "verified_at",
        )
        if (
            record.get("local_status") != "verified"
            or any(
                not isinstance(record.get(key), str) or not record[key].strip()
                for key in required_strings
            )
            or not isinstance(conditions, list)
            or not conditions
            or any(not isinstance(value, str) or not value.strip() for value in conditions)
            or not _non_url_locator(record.get("locator"))
            or not _valid_iso_datetime(record.get("recorded_at"))
            or not _valid_iso_datetime(record.get("verified_at"))
        ):
            continue
        result.append(record)
    return result


def derive_verification_level(entry: "KnowledgeEntry") -> str:
    """Derive one mutually exclusive level from locally auditable evidence.

    Provenance and imported claims affect review priority only. They never
    elevate a claim. Conflict remains a verifier result rather than persisted
    evidence state.
    """
    if entry.is_signed_off():
        return "expert_verified"
    if verified_field_records(entry):
        return "field_tested"
    if len(verified_references(entry)) >= 2:
        return "cross_ref"
    return "unverified"


def is_high_risk_knowledge(entry: "KnowledgeEntry") -> bool:
    """Conservative v1 hazard heuristic pending SHA-241 domain review.

    Whole categories are intentionally over-classified when a bad instruction
    can plausibly cause injury, fire/explosion, electrocution, structural
    failure, poisoning, or violent escalation. This is a fail-safe review
    queue, not a claim that category names fully model risk.
    """
    if entry.review_status != "approved":
        return True
    if "unknown" in entry.hazards:
        return True
    if entry.risk_level in {"pending_review", "high", "critical"}:
        return True
    if entry.risk_level in {"low", "medium"}:
        return False
    category = canonical_source_id(entry.category or "")
    subcategory = canonical_source_id(entry.subcategory or "")
    return (
        entry.priority == 0
        or category in {
            "medical", "medicine", "health", "chemistry", "energy",
            "engineering", "defense", "mechanical",
        }
        or any(token in subcategory for token in ("medical", "health", "first_aid"))
    )


def externalize_knowledge_evidence(entry: "KnowledgeEntry") -> None:
    """Keep imported evidence claims while removing local trust assertions."""
    if not entry.review_claim:
        entry.review_claim = review_claim_payload(entry)
    if entry.review_claim:
        entry.review_claim["local_status"] = "external_claim"
    for values in (entry.references, entry.field_records):
        for value in values:
            if not isinstance(value, dict):
                continue
            value["local_status"] = "external_claim"
            value.pop("verified_by", None)
            value.pop("verified_at", None)
    entry.reviewer = ""
    entry.qualification = ""
    entry.review_date = ""
    entry.citation = ""
    entry.content_hash = ""
    entry.signoff_version = 0
    if entry.risk_reviews:
        entry.risk_review_claims = [
            *[dict(value) for value in entry.risk_review_claims],
            *[dict(value) for value in entry.risk_reviews],
        ]
    entry.risk_reviews = []
    entry.review_status = "pending_external_review"
    if not entry.risk_level:
        entry.risk_level = "pending_review"
    if not entry.hazards:
        entry.hazards = ["unknown"]


def review_claim_payload(entry: "KnowledgeEntry") -> dict:
    """Return audit metadata without converting an external claim to trust."""
    if entry.review_claim:
        return dict(entry.review_claim)
    if all((
        entry.reviewer, entry.qualification, entry.review_date, entry.citation,
        entry.content_hash, entry.signoff_version > 0,
    )):
        return {
            "reviewer": entry.reviewer,
            "qualification": entry.qualification,
            "review_date": entry.review_date,
            "citation": entry.citation,
            "content_hash": entry.content_hash,
            "signoff_version": entry.signoff_version,
            "local_status": "local_verified" if entry.is_signed_off() else "local_invalid",
        }
    return {}


KNOWLEDGE_TRANSPORT_FIELDS = (
    "id", "category", "subcategory", "priority", "title", "summary",
    "steps", "prerequisites", "warnings", "references", "field_records",
    "applicable_when", "contraindications", "verification", "source",
    "verification_claim", "source_claim", "review_claim", "version", "language",
    "risk_level", "hazards", "review_status", "risk_reviews", "risk_review_claims",
)


def knowledge_transport_payload(entry: "KnowledgeEntry") -> dict:
    """Canonical semantic fields shared by Spark transport and signatures."""
    payload = {
        field: getattr(entry, field)
        for field in KNOWLEDGE_TRANSPORT_FIELDS
        if field != "review_claim"
    }
    payload["review_claim"] = review_claim_payload(entry)
    return payload


@dataclass
class ExperienceLog:
    id: str
    timestamp: str
    event: str
    outcome: str
    lesson: str = ""
    related_knowledge_id: str = ""


@dataclass
class MapPOI:
    id: str
    name: str
    type: str
    description: str = ""
    distance_km: float = 0.0
    direction: str = ""
    notes: str = ""
    discovered_at: str = ""
    verified: bool = False


@dataclass
class OperatingState:
    mode: str = "standard"
    power_remaining_hours: float = 48.0
    last_mode_change: str = ""
    # When True, automatic mode adaptation (based on power telemetry)
    # is suspended and the operator's explicit choice is honoured.
    # Set by /api/system/operating-mode and the equivalent CLI command.
    mode_manual_override: bool = False


@dataclass
class CommunityMember:
    id: str
    name: str
    role: str = "executor"
    domains: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    health_status: str = "unknown"
    psychological_stability: float = 0.5
    contribution_score: float = 0.0
    joined_at: str = ""
    last_active: str = ""
    is_commander: bool = False


@dataclass
class ConflictRecord:
    id: str
    title: str
    description: str = ""
    parties: list[str] = field(default_factory=list)
    status: str = "open"
    mediator: str = ""
    resolution: str = ""
    created_at: str = ""
    resolved_at: str = ""


@dataclass
class TradeOffer:
    id: str
    proposer_id: str
    target_spark_id: str
    offer_knowledge_ids: list[str] = field(default_factory=list)
    request_knowledge_ids: list[str] = field(default_factory=list)
    status: str = "proposed"
    created_at: str = ""
    completed_at: str = ""


@dataclass
class Goal:
    """PRD §10.1 目标系统 — 生存者需要达成的方向性成果"""
    id: str
    title: str
    description: str = ""
    goal_type: str = "auto"          # auto / manual
    category: str = "survival"        # survival / quality / exploration / community / civilization
    priority: str = "medium"          # critical / high / medium / low
    status: str = "active"            # active / completed / abandoned / paused
    source: str = "assessment"        # assessment / survivor / trade / experience
    progress: float = 0.0             # 0.0 - 1.0
    deadline: str = ""                # 可选截止日期
    created_at: str = ""
    updated_at: str = ""
    # 自动生成特有
    triggers: str = ""                # JSON 数组: 触发条件
    rationale: str = ""               # 为什么生成
    # 手动添加特有
    created_by: str = ""              # 生存者名字
    # 关联
    milestone_count: int = 0
    milestone_done: int = 0


@dataclass
class Milestone:
    """PRD §10.1 目标里程碑 — 目标的关键节点"""
    id: str
    goal_id: str
    description: str
    done: bool = False
    order: int = 0
    created_at: str = ""
    completed_at: str = ""


@dataclass
class DiaryEntry:
    """PRD §4.7 火种日记 — 生存者的个人记录"""
    id: str
    date: str                         # YYYY-MM-DD
    content: str
    emotion: str = "neutral"          # positive / neutral / negative
    keywords: str = ""                # JSON 数组
    related_goal_id: str = ""
    related_event: str = ""
    is_public: bool = False           # 多人场景是否公开
    created_at: str = ""


@dataclass
class TimelineEvent:
    """PRD §4.4 生存时间线 — 自动记录的关键事件"""
    id: str
    day: int                          # Day N
    timestamp: str
    event_type: str                   # 见 TimelineEventType
    title: str
    description: str = ""
    emotion: str = "neutral"
    related_goal_id: str = ""
    auto_generated: bool = True


@dataclass
class ActionPlan:
    """PRD §3.1.3 资源预警协议 — 行动方案"""
    id: str
    warning_id: str                   # 关联的预警资源类型
    resource_type: str                # 资源类型
    solution_source: str              # knowledge / fallback
    steps: list[str] = field(default_factory=list)
    rank_score: float = 0.0
    status: str = "proposed"          # proposed / accepted / executing / failed / completed
    created_at: str = ""
    updated_at: str = ""
    result: str = ""
    title: str = ""                   # 方案标题
