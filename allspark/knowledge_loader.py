from allspark.models import KnowledgeEntry


def load_knowledge(tier: int = -1, language: str = "") -> list[KnowledgeEntry]:
    entries = []
    if tier < 0 or tier == 0:
        if language == "en":
            from allspark.knowledge_data_en import get_tier0_knowledge_en
            entries.extend(get_tier0_knowledge_en())
        else:
            from allspark.knowledge_data import get_tier0_knowledge
            entries.extend(get_tier0_knowledge())
            if language == "en":
                from allspark.knowledge_data_en import get_tier0_knowledge_en
                entries.extend(get_tier0_knowledge_en())
    if tier < 0 or tier in (1, 2):
        from allspark.knowledge_data_tier12 import get_tier1_knowledge, get_tier2_knowledge
        if tier < 0 or tier == 1:
            entries.extend(get_tier1_knowledge())
        if tier < 0 or tier == 2:
            entries.extend(get_tier2_knowledge())
    if tier < 0 or tier == 3:
        from allspark.knowledge_data_tier3 import get_tier3_knowledge
        entries.extend(get_tier3_knowledge())
    return entries


def load_all_knowledge(language: str = "zh") -> list[KnowledgeEntry]:
    return load_knowledge(tier=-1, language=language)


def get_tier_info() -> dict:
    return {
        0: {"name": "立即生存", "name_en": "Immediate Survival", "file": "knowledge_data.py"},
        1: {"name": "短期生存", "name_en": "Short-term Survival", "file": "knowledge_data_tier12.py"},
        2: {"name": "中期自给", "name_en": "Mid-term Self-sufficiency", "file": "knowledge_data_tier12.py"},
        3: {"name": "长期社区", "name_en": "Long-term Community", "file": "knowledge_data_tier3.py"},
    }
