"""Machine-reproducible safety audit for bundled knowledge (SHA-240)."""

from allspark.core.models import derive_verification_level, is_high_risk_knowledge
from allspark.services.knowledge_loader import load_knowledge


def audit_bundled_knowledge() -> dict:
    entries = load_knowledge()
    high_risk = [entry for entry in entries if is_high_risk_knowledge(entry)]
    violations = []
    legacy_levels = []
    for entry in entries:
        derived = derive_verification_level(entry)
        if entry.verification in {"field_tested", "experience_based", "partially_verified"}:
            legacy_levels.append(entry.id)
        if is_high_risk_knowledge(entry) and not (
            derived in {"expert_verified", "cross_ref", "field_tested"}
            or entry.verification == "unverified"
        ):
            violations.append(entry.id)
    return {
        "classification_mode": "conservative_category_heuristic",
        "classification_limit": "May over- or under-classify until named domain review (SHA-241)",
        "total": len(entries),
        "high_risk": len(high_risk),
        "verified_high_risk": sum(
            derive_verification_level(entry) != "unverified" for entry in high_risk
        ),
        "unverified_high_risk": sum(
            entry.verification == "unverified" for entry in high_risk
        ),
        "violations": violations,
        "legacy_level_entries": legacy_levels,
    }
