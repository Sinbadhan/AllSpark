import logging

from allspark.core.database import Database
from allspark.core.i18n import get_language, t
from allspark.core.models import (
    ResourceType,
    derive_verification_level,
    is_high_risk_knowledge,
    verified_field_records,
    verified_references,
)

logger = logging.getLogger(__name__)


def _risk_qualification_label(value: object) -> str:
    code = value if isinstance(value, str) else ""
    key = f"knowledge_risk_qualification_{code}"
    label = t(key)
    if label != key:
        return label
    readable = code.replace("_", " ").strip() or t("knowledge_not_provided")
    return t("knowledge_risk_qualification_unknown", qualification=readable)


class KnowledgeEngine:
    def __init__(self, db: Database, vector_engine=None, external_kb=None):
        self.db = db
        self.vector_engine = vector_engine
        self.external_kb = external_kb

    def search(self, query: str, limit: int = 10) -> list:
        if self.vector_engine and self.vector_engine.is_available():
            return self.vector_engine.hybrid_search(query, limit)
        return self.db.search_knowledge(query, limit)

    def search_external(self, query: str, limit: int = 10) -> dict:
        """Search optional external offline KBs (Kiwix/Kolibri/ProtoMaps)."""
        if self.external_kb and self.external_kb.is_available():
            return self.external_kb.search_all(query, limit)
        return {}

    def search_all_sources(self, query: str, limit: int = 10) -> dict:
        """Return local and external results without changing the local search API."""
        return {
            "local": self.search(query, limit),
            "external": self.search_external(query, limit),
        }

    def search_by_language(self, query: str, limit: int = 10) -> list:
        lang = get_language()
        lang_results = self.db.search_knowledge(query, limit, language=lang)
        if lang_results:
            return lang_results[:limit]
        return self.db.search_knowledge(query, limit)

    def get_by_category(self, category: str, subcategory: str = "") -> list:
        return self.db.get_knowledge_by_category(category, subcategory)

    def get_tier(self, max_priority: int = 0) -> list:
        return self.db.get_knowledge_by_priority(max_priority)

    def get_categories(self) -> list[str]:
        rows = self.db.conn.execute(
            "SELECT DISTINCT category FROM knowledge ORDER BY category"
        ).fetchall()
        return [r[0] for r in rows]

    def get_subcategories(self, category: str) -> list[str]:
        rows = self.db.conn.execute(
            "SELECT DISTINCT subcategory FROM knowledge WHERE category=? ORDER BY subcategory",
            (category,)
        ).fetchall()
        return [r[0] for r in rows]

    @staticmethod
    def entry_payload(entry, *, detail: bool = True) -> dict:
        """One derived truth contract for API, Repository and Q&A."""
        level = derive_verification_level(entry)
        source_keys = {
            "pre_collapse": "knowledge_source_bundled",
            "other_spark": "knowledge_source_external",
            "self_learned": "knowledge_source_local_generated",
            "self_learned_llm": "knowledge_source_ai_generated",
        }
        high_risk = is_high_risk_knowledge(entry)
        local_references = verified_references(entry)
        local_field_records = verified_field_records(entry)
        verified_reference_ids = {id(value) for value in local_references}
        verified_field_ids = {id(value) for value in local_field_records}
        payload = {
            "id": entry.id,
            "category": entry.category,
            "subcategory": entry.subcategory,
            "priority": entry.priority,
            "title": entry.title,
            "summary": entry.summary,
            "verification": level,
            "verification_label": t(f"knowledge_verification_{level}_label"),
            "verification_explanation": t(
                f"knowledge_verification_{level}_explanation"
            ),
            "source": entry.source,
            "source_label": t(source_keys.get(entry.source, "knowledge_source_other")),
            "language": entry.language,
            "high_risk": high_risk,
            "risk_level": entry.risk_level or "pending_review",
            "risk_level_label": t(
                f"knowledge_risk_level_{entry.risk_level or 'pending_review'}"
            ),
            "hazards": entry.hazards or ["unknown"],
            "hazard_labels": [
                t(f"knowledge_hazard_{hazard}")
                for hazard in (entry.hazards or ["unknown"])
            ],
            "risk_review_status": entry.review_status or "pending_external_review",
            "risk_review_status_label": t(
                "knowledge_risk_review_status_"
                f"{entry.review_status or 'pending_external_review'}"
            ),
            "risk_review_counts": {
                "local": len(entry.risk_reviews),
                "external_claims": len(entry.risk_review_claims),
            },
            "risk_notice": (
                t("knowledge_high_risk_unverified_notice")
                if high_risk and level == "unverified" else ""
            ),
            "escalation_help": (
                t("knowledge_escalation_help") if high_risk else ""
            ),
            "evidence_counts": {
                "verified_references": len(local_references),
                "verified_field_records": len(local_field_records),
                "external_reference_claims": len(entry.references) - len(local_references),
                "external_field_claims": len(entry.field_records) - len(local_field_records),
                "local_expert_reviews": 1 if entry.is_signed_off() else 0,
                "external_review_claims": 1 if entry.review_claim else 0,
            },
        }
        if detail:
            references = [
                {
                    **value,
                    "trust_status": (
                        "local_verified" if id(value) in verified_reference_ids
                        else "external_claim"
                    ),
                    "trust_label": t(
                        "knowledge_local_verified_evidence"
                        if id(value) in verified_reference_ids
                        else "knowledge_external_unverified_claim"
                    ),
                }
                for value in entry.references
            ]
            field_records = [
                {
                    **value,
                    "trust_status": (
                        "local_verified" if id(value) in verified_field_ids
                        else "external_claim"
                    ),
                    "trust_label": t(
                        "knowledge_local_verified_evidence"
                        if id(value) in verified_field_ids
                        else "knowledge_external_unverified_claim"
                    ),
                }
                for value in entry.field_records
            ]
            payload.update({
                "steps": entry.steps,
                "prerequisites": entry.prerequisites,
                "warnings": entry.warnings,
                "verification_claim": entry.verification_claim,
                "source_claim": entry.source_claim,
                "risk_reviews": [
                    {
                        **review,
                        "qualification_label": _risk_qualification_label(
                            review.get("qualification_type")
                        ),
                        "trust_status": "local_verified",
                        "trust_label": t("knowledge_local_risk_review"),
                    }
                    for review in entry.risk_reviews
                ],
                "risk_review_claims": [
                    {
                        **review,
                        "qualification_label": _risk_qualification_label(
                            review.get("qualification_type")
                        ),
                        "trust_status": "external_claim",
                        "trust_label": t("knowledge_external_risk_review_claim"),
                    }
                    for review in entry.risk_review_claims
                ],
                "references": references,
                "field_records": field_records,
                "applicable_when": entry.applicable_when,
                "contraindications": entry.contraindications,
                "local_review": (
                    {
                        "reviewer": entry.reviewer,
                        "qualification": entry.qualification,
                        "review_date": entry.review_date,
                        "citation": entry.citation,
                        "content_hash": entry.content_hash,
                        "signoff_version": entry.signoff_version,
                        "trust_status": "local_verified",
                        "trust_label": t("knowledge_local_verified_review"),
                    }
                    if entry.is_signed_off() else {}
                ),
                "external_review_claim": (
                    {
                        **entry.review_claim,
                        "trust_status": "external_claim",
                        "trust_label": t("knowledge_external_review_claim"),
                    }
                    if entry.review_claim else {}
                ),
            })
        return payload

    def format_entry(self, entry) -> str:
        payload = self.entry_payload(entry)
        lines = [f"[{entry.id}] {entry.title}"]
        lines.append(f"  {t('category')}: {entry.category}/{entry.subcategory} | {t('priority')}: {t('tier')} {entry.priority}")
        lines.append(f"  {entry.summary}")
        lines.append(
            f"  {t('verification')}: {payload['verification_label']} — "
            f"{payload['verification_explanation']}"
        )
        lines.append(f"  {t('source')}: {payload['source_label']}")
        lines.append(
            f"  {t('knowledge_risk_classification_label')}: "
            f"{payload['risk_review_status_label']} · {payload['risk_level_label']}"
        )
        lines.append(
            f"  {t('knowledge_hazards_label')}: "
            f"{', '.join(payload['hazard_labels'])}"
        )
        if payload["risk_notice"]:
            lines.append(f"  {t('knowledge_risk_label')}: {payload['risk_notice']}")
        lines.append(
            f"  {t('knowledge_applicable_when')}: "
            f"{'; '.join(entry.applicable_when) if entry.applicable_when else t('knowledge_not_provided')}"
        )
        lines.append(
            f"  {t('knowledge_contraindications')}: "
            f"{'; '.join(entry.contraindications) if entry.contraindications else t('knowledge_not_provided')}"
        )
        if payload["escalation_help"]:
            lines.append(f"  {t('knowledge_escalation_label')}: {payload['escalation_help']}")
        if payload["references"]:
            lines.append(f"  {t('knowledge_references_label')}:")
            for reference in payload["references"]:
                name = (
                    reference.get("title") or reference.get("organization")
                    or reference.get("source_id") or t("knowledge_not_provided")
                )
                lines.append(
                    f"    - {reference['trust_label']}: {name} — "
                    f"{reference.get('locator', '')}"
                )
        if payload["field_records"]:
            lines.append(f"  {t('knowledge_field_records_label')}:")
            for record in payload["field_records"]:
                lines.append(
                    f"    - {record['trust_label']}: "
                    f"{t('knowledge_field_source')}={record.get('source_id', '')}; "
                    f"{t('knowledge_field_conditions')}="
                    f"{'; '.join(record.get('conditions', []))}; "
                    f"{t('knowledge_field_outcome')}={record.get('outcome', '')}; "
                    f"{t('knowledge_field_date')}={record.get('recorded_at', '')}; "
                    f"{t('knowledge_field_locator')}={record.get('locator', '')}"
                )
        for review in (payload["local_review"], payload["external_review_claim"]):
            if review:
                lines.append(
                    f"  {review['trust_label']}: "
                    f"{t('knowledge_review_reviewer')}={review.get('reviewer', '')}; "
                    f"{t('knowledge_review_qualification')}="
                    f"{review.get('qualification', '')}; "
                    f"{t('knowledge_review_date')}={review.get('review_date', '')}; "
                    f"{t('knowledge_review_citation')}={review.get('citation', '')}; "
                    f"{t('knowledge_review_version')}={review.get('signoff_version', '')}; "
                    f"{t('knowledge_review_fingerprint')}={review.get('content_hash', '')}"
                )
        for review in [*payload["risk_reviews"], *payload["risk_review_claims"]]:
            lines.append(
                f"  {review['trust_label']}: "
                f"{t('knowledge_review_reviewer')}={review.get('reviewer', '')}; "
                f"{t('knowledge_review_qualification')}="
                f"{review.get('qualification_label', '')}; "
                f"{t('knowledge_risk_qualification_evidence')}="
                f"{review.get('qualification_evidence', '')}; "
                f"{t('knowledge_hazards_label')}="
                f"{', '.join(review.get('covered_hazards', []))}; "
                f"{t('knowledge_review_date')}={review.get('reviewed_at', '')}; "
                f"{t('knowledge_risk_conclusion')}="
                f"{review.get('conclusion', '')}; "
                f"{t('knowledge_risk_reservations')}="
                f"{'; '.join(review.get('reservations', [])) or t('knowledge_not_provided')}; "
                f"{t('knowledge_review_fingerprint')}="
                f"{review.get('classification_hash', '')}"
            )
        if entry.prerequisites:
            lines.append(f"  {t('prerequisites')}: {', '.join(entry.prerequisites)}")
        if entry.warnings:
            lines.append(f"  {t('warnings_label')}:")
            for w in entry.warnings:
                lines.append(f"    - {w}")
        if entry.steps:
            lines.append(f"  {t('steps')}:")
            for i, step in enumerate(entry.steps, 1):
                lines.append(f"    {i}. {step}")
        return "\n".join(lines)

    def format_answer(self, entries: list) -> str:
        """SHA-150: render 1 main answer (full) + up to 2 related links.

        Replaces concatenating multiple full entries, which buried key actions
        under a wall of text in both CLI and Web chat. The main entry already
        carries source + verification level via format_entry; related entries
        are shown as title+id links only.
        """
        if not entries:
            return t("no_knowledge_match")
        lines = [self.format_entry(entries[0])]
        related = entries[1:3]
        if related:
            lines.append("")
            lines.append(t("related_knowledge"))
            for e in related:
                payload = self.entry_payload(e)
                lines.append(
                    f"  • [{e.id}] {e.title} — {payload['verification_label']}"
                )
        return "\n".join(lines)

    def get_relevant_knowledge(self, intent: str, resources: list = None) -> list:
        entries = self.search_by_language(intent, limit=5)
        if not entries and resources:
            for r in resources:
                if not r.amount_known:
                    continue
                rates_known = r.consumption_known and r.intake_known
                if r.type == ResourceType.WATER and rates_known and r.estimated_remaining_hours < 72:
                    entries.extend(self.search_by_language("水 净水 水源 water purify", limit=3))
                elif r.type == ResourceType.FOOD and rates_known and r.estimated_remaining_hours < 120:
                    entries.extend(self.search_by_language("食物 可食用 狩猎 food edible", limit=3))
                elif r.type == ResourceType.FIRE and r.current_amount < 10:
                    entries.extend(self.search_by_language("火 生火 点火 fire ignite", limit=3))
        seen = set()
        unique = []
        for e in entries:
            if e.id not in seen:
                seen.add(e.id)
                unique.append(e)
        return unique[:10]
