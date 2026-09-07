"""Read-only AS-11 inventory; reports gaps without inventing risk approvals."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from allspark.core.models import (
    KnowledgeEntry,
    compute_content_hash,
    compute_risk_classification_hash,
    derive_verification_level,
    is_actionable_knowledge,
    verified_references,
)
from allspark.services.knowledge_loader import load_knowledge


def inventory(entries: list[KnowledgeEntry]) -> dict:
    identities = Counter((entry.id, entry.language) for entry in entries)
    languages: dict[str, set[str]] = defaultdict(set)
    records = []
    for entry in entries:
        # The bundled English contract uses the Chinese topic ID plus /en.
        # This checks identity pairing only, not semantic translation quality.
        topic_id = entry.id.removesuffix("/en") if entry.language == "en" else entry.id
        languages[topic_id].add(entry.language)
        gaps = []
        for missing, key in (
            (not entry.references, "source_reference_missing"),
            (not verified_references(entry), "locally_verified_reference_missing"),
            (not entry.applicable_when, "applicability_missing"),
            (not entry.contraindications, "contraindications_missing"),
            (derive_verification_level(entry) == "unverified", "content_evidence_missing"),
            (entry.review_status != "approved", "risk_approval_missing"),
            ("unknown" in entry.hazards, "risk_classification_pending"),
        ):
            if missing:
                gaps.append(key)
        records.append({
            "id": entry.id, "topic_id": topic_id,
            "language": entry.language, "tier": entry.priority,
            "title": entry.title, "category": entry.category,
            "subcategory": entry.subcategory,
            "content_hash": compute_content_hash(entry),
            "classification_hash": compute_risk_classification_hash(entry),
            "risk_level": entry.risk_level, "hazards": entry.hazards,
            "review_status": entry.review_status,
            "actionable": is_actionable_knowledge(entry), "gaps": gaps,
        })
    duplicates = [list(key) for key, count in sorted(identities.items()) if count != 1]
    incomplete = [key for key, value in sorted(languages.items()) if value != {"zh", "en"}]
    integrity = bool(entries) and not duplicates and not incomplete
    return {
        "purpose": "evidence gaps only; not named domain review or translation approval",
        "record_count": len(entries), "topic_count": len(languages),
        "tier_language_counts": {
            language: dict(sorted(Counter(
                entry.priority for entry in entries if entry.language == language
            ).items())) for language in ("zh", "en")
        },
        "duplicate_identities": duplicates, "incomplete_bilingual_topics": incomplete,
        "inventory_integrity": "passed" if integrity else "failed",
        "actionable_count": sum(record["actionable"] for record in records),
        "content_risk_gate": "passed" if integrity and all(
            record["actionable"] for record in records
        ) else "blocked",
        "gap_counts": dict(sorted(Counter(
            gap for record in records for gap in record["gaps"]
        ).items())),
        "records": sorted(records, key=lambda record: (record["tier"], record["id"], record["language"])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-reviewed", action="store_true")
    args = parser.parse_args()
    report = inventory(load_knowledge())
    sys.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n")
    if report["inventory_integrity"] != "passed":
        return 2
    return int(args.require_reviewed and report["content_risk_gate"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
