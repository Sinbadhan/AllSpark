import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from allspark.models import KnowledgeEntry


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


TRUSTED_SOURCES = {"pre_collapse", "expert_verified", "field_tested"}
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

        report.overall_passed = all(r.passed for r in report.results)
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
        verification = entry.verification or "unverified"

        if source in TRUSTED_SOURCES:
            trust = "high"
        elif source in MODERATE_SOURCES:
            trust = "moderate"
        else:
            trust = "low"

        if verification == "expert_verified":
            trust = "high"
        elif verification == "field_tested":
            trust = "high"
        elif verification == "cross_ref":
            trust = "moderate"

        return VerificationResult(
            step=VerificationStep.SOURCE_CHECK.value,
            passed=trust != "low",
            message=f"Source trust level: {trust} (source={source}, verification={verification})",
            details={"source": source, "verification": verification, "trust_level": trust},
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
        if not self.db:
            return VerificationResult(
                step=VerificationStep.CROSS_REFERENCE.value,
                passed=True,
                message="No database available, skipping cross-reference",
                details={"skipped": True},
            )

        supporting = []
        contradicting = []

        keywords = []
        if entry.title:
            keywords.extend(entry.title.split())
        if entry.summary:
            keywords.extend(entry.summary.split()[:10])

        keywords = [k for k in keywords if len(k) >= 2][:8]

        for kw in keywords:
            results = self.db.search_knowledge(kw, limit=3)
            for r in results:
                if r.id == entry.id:
                    continue
                if r.category == entry.category:
                    supporting.append({"id": r.id, "title": r.title, "reason": "same_category"})
                elif any(kw in (r.summary or "") for kw in keywords[:3]):
                    supporting.append({"id": r.id, "title": r.title, "reason": "keyword_overlap"})

        supporting = self._deduplicate_refs(supporting)

        return VerificationResult(
            step=VerificationStep.CROSS_REFERENCE.value,
            passed=len(supporting) > 0 or len(keywords) < 3,
            message=f"Found {len(supporting)} supporting reference(s)" if supporting else "No supporting references found",
            details={"supporting_count": len(supporting), "supporting": supporting[:5], "keywords_used": keywords},
        )

    def _step_level_assign(self, entry: KnowledgeEntry, report: VerificationReport) -> VerificationResult:
        source_result = next((r for r in report.results if r.step == VerificationStep.SOURCE_CHECK.value), None)
        consistency_result = next((r for r in report.results if r.step == VerificationStep.CONSISTENCY_CHECK.value), None)
        cross_ref_result = next((r for r in report.results if r.step == VerificationStep.CROSS_REFERENCE.value), None)

        source_trust = "low"
        if source_result and source_result.details:
            source_trust = source_result.details.get("trust_level", "low")

        has_conflicts = consistency_result and not consistency_result.passed
        has_support = cross_ref_result and cross_ref_result.passed

        if has_conflicts:
            level = VerificationLevel.CONFLICT
        elif source_trust == "high" and has_support:
            level = VerificationLevel.EXPERT_VERIFIED
        elif source_trust == "high":
            level = VerificationLevel.PARTIALLY_VERIFIED
        elif source_trust == "moderate" and has_support:
            level = VerificationLevel.CROSS_REFERENCED
        elif source_trust == "moderate":
            level = VerificationLevel.PARTIALLY_VERIFIED
        elif has_support:
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
