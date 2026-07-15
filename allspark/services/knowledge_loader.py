import logging
from pathlib import Path

import yaml

from allspark.core.i18n import t
from allspark.core.models import (
    KnowledgeEntry,
    derive_verification_level,
    normalize_knowledge_evidence,
)

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "knowledge"

_TIER_FILES = {
    0: {"zh": "tier0_zh.yaml", "en": "tier0_en.yaml"},
    1: {"zh": "tier1_zh.yaml", "en": "tier1_en.yaml"},
    2: {"zh": "tier2_zh.yaml", "en": "tier2_en.yaml"},
    3: {"zh": "tier3_zh.yaml", "en": "tier3_en.yaml"},
}


def _load_yaml(path: Path) -> list[dict]:
    """Load a YAML file and return list of dicts."""
    if not path.exists():
        logger.warning("Knowledge YAML not found: %s", path)
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, list) else []


def _dict_to_entry(d: dict) -> KnowledgeEntry:
    """Convert a dict to a KnowledgeEntry."""
    entry = KnowledgeEntry(
        id=d["id"],
        category=d["category"],
        subcategory=d["subcategory"],
        priority=d.get("priority", 0),
        title=d["title"],
        summary=d["summary"],
        steps=d.get("steps", []),
        prerequisites=d.get("prerequisites", []),
        warnings=d.get("warnings", []),
        verification="unverified",
        source=d.get("source", "pre_collapse"),
        verification_claim=d.get("verification", "unverified"),
        references=d.get("references", []),
        field_records=d.get("field_records", []),
        applicable_when=d.get("applicable_when", []),
        contraindications=d.get("contraindications", []),
        review_claim=d.get("review_claim", {}),
        language=d.get("language", "zh"),
        # SHA-148: auditable signoff fields (all empty/0 by default).
        reviewer=d.get("reviewer", ""),
        qualification=d.get("qualification", ""),
        review_date=d.get("review_date", ""),
        citation=d.get("citation", ""),
        content_hash=d.get("content_hash", ""),
        signoff_version=d.get("signoff_version", 0),
    )
    normalize_knowledge_evidence(entry)
    entry.verification = derive_verification_level(entry)
    if entry.verification_claim != entry.verification:
        logger.debug(
            "Knowledge %s claims %s without local auditable evidence; "
            "deriving %s",
            entry.id, entry.verification_claim, entry.verification,
        )
    return entry


def load_knowledge(tier: int = -1, language: str = "") -> list[KnowledgeEntry]:
    """Load knowledge entries from YAML files.

    Args:
        tier: Knowledge tier (-1 for all, 0-3 for specific tier)
        language: Language filter ("zh", "en", or "" for all)
    """
    entries: list[KnowledgeEntry] = []

    tiers_to_load = list(range(4)) if tier < 0 else [tier]

    for tier_num in tiers_to_load:
        tier_files = _TIER_FILES.get(tier_num, {})
        for lang, filename in tier_files.items():
            # Skip if a specific language is requested and doesn't match
            if language and lang != language:
                continue
            path = _DATA_DIR / filename
            raw_entries = _load_yaml(path)
            for d in raw_entries:
                entries.append(_dict_to_entry(d))

    return entries


def load_all_knowledge(language: str = "zh") -> list[KnowledgeEntry]:
    """Load all knowledge entries for the given language."""
    return load_knowledge(tier=-1, language=language)


def get_tier_info() -> dict:
    return {
        0: {"name": t("tier0_name"), "name_en": "Immediate Survival", "file": "tier0_zh.yaml"},
        1: {"name": t("tier1_name"), "name_en": "Short-term Survival", "file": "tier1_zh.yaml"},
        2: {"name": t("tier2_name"), "name_en": "Mid-term Self-sufficiency", "file": "tier2_zh.yaml"},
        3: {"name": t("tier3_name"), "name_en": "Long-term Community", "file": "tier3_zh.yaml"},
    }
