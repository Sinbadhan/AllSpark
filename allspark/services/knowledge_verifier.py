import hashlib
import hmac
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum

from allspark.core.models import KnowledgeEntry

logger = logging.getLogger(__name__)


class VerificationLevel(Enum):
    EXPERT_VERIFIED = "expert_verified"
    CROSS_REFERENCED = "cross_ref"
    FIELD_TESTED = "field_tested"
    PARTIALLY_VERIFIED = "partially_verified"
    UNVERIFIED = "unverified"
    CONFLICT = "conflict"


class VerificationStep(Enum):
    FORMAT_CHECK = "format_check"
    SOURCE_CHECK = "source_check"
    CONSISTENCY_CHECK = "consistency_check"
    CROSS_REFERENCE = "cross_reference"
    LEVEL_ASSIGN = "level_assign"


@dataclass
class VerificationResult:
    step: str
    passed: bool
    message: str
    details: dict = field(default_factory=dict)


@dataclass
class VerificationReport:
    entry_id: str
    entry_title: str
    overall_passed: bool = False
    level: str = "unverified"
    results: list[VerificationResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "entry_title": self.entry_title,
            "overall_passed": self.overall_passed,
            "level": self.level,
            "results": [{"step": r.step, "passed": r.passed, "message": r.message, "details": r.details} for r in self.results],
            "warnings": self.warnings,
            "conflicts": self.conflicts,
        }


# Provenance and verification are separate taxonomies.  In particular,
# ``expert_verified`` and ``field_tested`` are evidence claims, not sources.
TRUSTED_SOURCES = {"pre_collapse"}
MODERATE_SOURCES = {"other_spark", "crowdsourced"}
LOW_TRUST_SOURCES = {"unverified", "unknown", "ai_generated"}

REQUIRED_FIELDS = ["id", "title", "summary", "category"]
RECOMMENDED_FIELDS = ["steps", "warnings", "priority"]
VALID_CATEGORIES = {"survival", "medical", "agriculture", "engineering", "science", "history", "social"}
VALID_PRIORITIES = {0, 1, 2, 3}
VALID_VERIFICATIONS = {v.value for v in VerificationLevel}


class KnowledgeVerifier:
    def __init__(self, db=None, llm_engine=None):
        self.db = db
        self.llm = llm_engine

    def verify_entry(self, entry: KnowledgeEntry) -> VerificationReport:
        report = VerificationReport(
            entry_id=entry.id,
            entry_title=entry.title,
        )

        report.results.append(self._step_format_check(entry))
        report.results.append(self._step_source_check(entry))
        report.results.append(self._step_consistency_check(entry))
        report.results.append(self._step_cross_reference(entry))
        report.results.append(self._step_level_assign(entry, report))

        # ``overall_passed`` means that one auditable verification path was
        # established and the hard content checks passed.  Cross-reference
        # and expert signoff are alternative evidence paths, so an expert-
        # signed entry is not failed merely because it has no cross-reference.
        hard_steps = {
            VerificationStep.FORMAT_CHECK.value,
            VerificationStep.CONSISTENCY_CHECK.value,
            VerificationStep.LEVEL_ASSIGN.value,
        }
        hard_checks_passed = all(
            result.passed for result in report.results if result.step in hard_steps
        )
        report.overall_passed = hard_checks_passed and report.level in {
            VerificationLevel.EXPERT_VERIFIED.value,
            VerificationLevel.CROSS_REFERENCED.value,
        }
        if not report.overall_passed:
            failed = [r.step for r in report.results if not r.passed]
            report.warnings.append(f"Failed steps: {', '.join(failed)}")

        return report

    def verify_batch(self, entries: list[KnowledgeEntry]) -> list[VerificationReport]:
        reports = []
        for entry in entries:
            reports.append(self.verify_entry(entry))
        return reports

    def _step_format_check(self, entry: KnowledgeEntry) -> VerificationResult:
        missing = []
        for f in REQUIRED_FIELDS:
            val = getattr(entry, f, None)
            if not val and val != 0:
                missing.append(f)

        if missing:
            return VerificationResult(
                step=VerificationStep.FORMAT_CHECK.value,
                passed=False,
                message=f"Missing required fields: {', '.join(missing)}",
                details={"missing_fields": missing},
            )

        warnings = []
        for f in RECOMMENDED_FIELDS:
            val = getattr(entry, f, None)
            if not val and val != 0:
                warnings.append(f)

        if entry.category not in VALID_CATEGORIES:
            warnings.append(f"Unusual category: {entry.category}")

        if entry.priority not in VALID_PRIORITIES:
            return VerificationResult(
                step=VerificationStep.FORMAT_CHECK.value,
                passed=False,
                message=f"Invalid priority: {entry.priority}",
                details={"invalid_priority": entry.priority},
            )

        msg = "Format check passed"
        if warnings:
            msg += f" (warnings: {', '.join(warnings)})"

        return VerificationResult(
            step=VerificationStep.FORMAT_CHECK.value,
            passed=True,
            message=msg,
            details={"warnings": warnings},
        )

    def _step_source_check(self, entry: KnowledgeEntry) -> VerificationResult:
        source = entry.source or "unknown"
        verification_claim = entry.verification or "unverified"

        if source in TRUSTED_SOURCES:
            trust = "high"
        elif source in MODERATE_SOURCES:
            trust = "moderate"
        else:
            trust = "low"

        return VerificationResult(
            step=VerificationStep.SOURCE_CHECK.value,
            passed=trust != "low",
            message=(
                f"Source trust level: {trust} "
                f"(source={source}, verification_claim={verification_claim})"
            ),
            details={
                "source": source,
                "verification_claim": verification_claim,
                "trust_level": trust,
            },
        )

    def _step_consistency_check(self, entry: KnowledgeEntry) -> VerificationResult:
        if not self.db:
            return VerificationResult(
                step=VerificationStep.CONSISTENCY_CHECK.value,
                passed=True,
                message="No database available, skipping consistency check",
                details={"skipped": True},
            )

        conflicts = []
        existing = self.db.get_knowledge(entry.id)
        if existing:
            if existing.summary and entry.summary:
                if self._is_contradictory(existing.summary, entry.summary):
                    conflicts.append({
                        "type": "summary_conflict",
                        "existing": existing.summary[:100],
                        "new": entry.summary[:100],
                    })

            if existing.steps and entry.steps:
                for i, (old_step, new_step) in enumerate(zip(existing.steps, entry.steps)):
                    if self._is_contradictory(old_step, new_step):
                        conflicts.append({
                            "type": "step_conflict",
                            "step_index": i,
                            "existing": old_step[:80],
                            "new": new_step[:80],
                        })

        same_category = self.db.get_knowledge_by_category(entry.category, entry.subcategory)
        for other in same_category:
            if other.id == entry.id:
                continue
            if other.warnings and entry.warnings:
                for w_old in other.warnings:
                    for w_new in entry.warnings:
                        if self._is_contradictory(w_old, w_new):
                            conflicts.append({
                                "type": "warning_conflict",
                                "conflict_with": other.id,
                                "existing": w_old[:80],
                                "new": w_new[:80],
                            })

        return VerificationResult(
            step=VerificationStep.CONSISTENCY_CHECK.value,
            passed=len(conflicts) == 0,
            message=f"Found {len(conflicts)} conflict(s)" if conflicts else "No conflicts found",
            details={"conflict_count": len(conflicts), "conflicts": conflicts[:5]},
        )

    def _step_cross_reference(self, entry: KnowledgeEntry) -> VerificationResult:
        # SHA-250: database presence, category similarity, and keyword overlap
        # are discovery signals, not evidence.  The current KnowledgeEntry
        # schema cannot represent two independent, locatable references; that
        # evidence model belongs to SHA-240.  Until then this step must fail
        # closed instead of fabricating support from search results.
        if not self.db:
            return VerificationResult(
                step=VerificationStep.CROSS_REFERENCE.value,
                passed=False,
                message="Cross-reference evidence not established: no database available",
                details={
                    "skipped": True,
                    "supporting_count": 0,
                    "supporting": [],
                    "reason": "independent_locatable_references_required",
                },
            )

        return VerificationResult(
            step=VerificationStep.CROSS_REFERENCE.value,
            passed=False,
            message="No auditable independent references available",
            details={
                "skipped": False,
                "supporting_count": 0,
                "supporting": [],
                "reason": "independent_locatable_references_required",
            },
        )

    def _step_level_assign(self, entry: KnowledgeEntry, report: VerificationReport) -> VerificationResult:
        source_result = next((r for r in report.results if r.step == VerificationStep.SOURCE_CHECK.value), None)
        consistency_result = next((r for r in report.results if r.step == VerificationStep.CONSISTENCY_CHECK.value), None)
        cross_ref_result = next((r for r in report.results if r.step == VerificationStep.CROSS_REFERENCE.value), None)

        source_trust = "low"
        if source_result and source_result.details:
            source_trust = source_result.details.get("trust_level", "low")

        has_conflicts = consistency_result and not consistency_result.passed
        has_support = self._has_auditable_support(cross_ref_result)

        if has_conflicts:
            level = VerificationLevel.CONFLICT
        elif source_trust == "high" and entry.is_signed_off():
            level = VerificationLevel.EXPERT_VERIFIED
        elif has_support:
            level = VerificationLevel.CROSS_REFERENCED
        elif source_trust == "high":
            level = VerificationLevel.PARTIALLY_VERIFIED
        else:
            level = VerificationLevel.UNVERIFIED

        report.level = level.value

        return VerificationResult(
            step=VerificationStep.LEVEL_ASSIGN.value,
            passed=level != VerificationLevel.CONFLICT,
            message=f"Assigned verification level: {level.value}",
            details={"level": level.value, "source_trust": source_trust, "has_conflicts": has_conflicts, "has_support": has_support},
        )

    @staticmethod
    def _has_auditable_support(result: VerificationResult | None) -> bool:
        """Accept cross-reference support only when its evidence is explicit.

        SHA-240 will introduce the structured reference schema.  This guard is
        deliberately stricter than the current result producer so skipped or
        accidentally-passed empty results cannot become trust evidence again.
        """
        if result is None or not result.passed or not result.details:
            return False
        if result.details.get("skipped"):
            return False
        supporting = result.details.get("supporting")
        if not isinstance(supporting, list) or len(supporting) < 2:
            return False

        source_ids = set()
        for reference in supporting:
            if not isinstance(reference, dict):
                return False
            source_id = reference.get("source_id")
            locator = reference.get("locator")
            if (
                reference.get("independent") is not True
                or not isinstance(source_id, str)
                or not source_id.strip()
                or not isinstance(locator, str)
                or not locator.strip()
            ):
                return False
            source_ids.add(source_id.strip())
        return len(source_ids) >= 2

    def _is_contradictory(self, text_a: str, text_b: str) -> bool:
        if not text_a or not text_b:
            return False

        negation_patterns = [
            (r"不要|不可|不能|禁止|切勿|绝不能", r"应该|必须|需要|务必|一定要"),
            (r"不要|不可|不能|禁止|切勿|绝不能", r"可以|能够|允许"),
            (r"应该|必须|需要|务必", r"不要|不可|不能|禁止"),
            (r"可以|能够|允许", r"不要|不可|不能|禁止"),
            (r"do not|never|avoid|must not", r"should|must|need to|always"),
            (r"should|must|need to", r"do not|never|avoid|must not"),
        ]

        for neg_pattern, pos_pattern in negation_patterns:
            a_has_neg = bool(re.search(neg_pattern, text_a, re.IGNORECASE))
            b_has_pos = bool(re.search(pos_pattern, text_b, re.IGNORECASE))
            a_has_pos = bool(re.search(pos_pattern, text_a, re.IGNORECASE))
            b_has_neg = bool(re.search(neg_pattern, text_b, re.IGNORECASE))

            if (a_has_neg and b_has_pos) or (a_has_pos and b_has_neg):
                return True

        return False

    def _deduplicate_refs(self, refs: list[dict]) -> list[dict]:
        seen = set()
        result = []
        for r in refs:
            if r["id"] not in seen:
                seen.add(r["id"])
                result.append(r)
        return result


class KnowledgeSigner:
    """Sign and verify knowledge entries to detect tampering (PRD §12.3).

    Uses HMAC-SHA256 with a local secret key. This provides basic tamper
    detection for knowledge entries exchanged between AllSpark instances.
    """

    def __init__(self, secret_key: str = None, db=None):
        self.db = db
        if secret_key:
            self._key = secret_key.encode("utf-8")
        else:
            self._key = self._derive_key()

    def _derive_key(self) -> bytes:
        """Derive a per-node key from the database path.

        This key is only suitable for detecting local tampering of a node's
        own entries — it is NOT a shared secret and cannot verify signatures
        across nodes (each node's db_path differs). Cross-node signature
        verification requires a ``secret_key`` passed explicitly to the
        constructor (see ``SparkNetwork._get_shared_secret``). Falls back to
        a constant only when no db is available at all.
        """
        if self.db:
            try:
                db_path = str(getattr(self.db, "db_path", "") or "allspark-default")
                return hashlib.sha256(f"allspark-sig-{db_path}".encode()).digest()
            except Exception as e:
                logger.warning(f"Failed to derive signing key from DB path: {e}")
        return hashlib.sha256(b"allspark-default-signing-key").digest()

    def sign_entry(self, entry: KnowledgeEntry) -> str:
        """Generate an HMAC-SHA256 signature for a knowledge entry."""
        payload = self._entry_payload(entry)
        return hmac.new(self._key, payload.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify_entry(self, entry: KnowledgeEntry, signature: str) -> bool:
        """Verify that a knowledge entry matches its signature."""
        expected = self.sign_entry(entry)
        return hmac.compare_digest(expected, signature)

    def sign_batch(self, entries: list[KnowledgeEntry]) -> dict[str, str]:
        """Sign multiple entries, returning {entry_id: signature}."""
        return {e.id: self.sign_entry(e) for e in entries}

    def verify_batch(self, entries: list[KnowledgeEntry],
                     signatures: dict[str, str]) -> dict[str, bool]:
        """Verify multiple entries against their signatures."""
        results = {}
        for entry in entries:
            sig = signatures.get(entry.id)
            if sig is None:
                results[entry.id] = False
            else:
                results[entry.id] = self.verify_entry(entry, sig)
        return results

    def _entry_payload(self, entry: KnowledgeEntry) -> str:
        """Create a canonical string representation of an entry for signing."""
        parts = [
            entry.id or "",
            entry.title or "",
            entry.summary or "",
            entry.category or "",
            str(entry.priority),
            entry.source or "",
            json.dumps(entry.steps or [], ensure_ascii=False, sort_keys=True),
            json.dumps(entry.warnings or [], ensure_ascii=False, sort_keys=True),
        ]
        return "|".join(parts)
