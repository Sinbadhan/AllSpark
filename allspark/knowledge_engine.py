from allspark.database import Database
from allspark.models import ResourceType
from allspark.i18n import t, get_language


class KnowledgeEngine:
    def __init__(self, db: Database):
        self.db = db

    def search(self, query: str, limit: int = 10) -> list:
        return self.db.search_knowledge(query, limit)

    def search_by_language(self, query: str, limit: int = 10) -> list:
        lang = get_language()
        all_results = self.db.search_knowledge(query, limit * 2)
        lang_results = [e for e in all_results if e.language == lang]
        if not lang_results:
            return all_results[:limit]
        return lang_results[:limit]

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

    def format_entry(self, entry) -> str:
        lines = [f"[{entry.id}] {entry.title}"]
        lines.append(f"  {t('category')}: {entry.category}/{entry.subcategory} | {t('priority')}: {t('tier')} {entry.priority}")
        lines.append(f"  {entry.summary}")
        if entry.steps:
            lines.append(f"  {t('steps')}:")
            for i, step in enumerate(entry.steps, 1):
                lines.append(f"    {i}. {step}")
        if entry.prerequisites:
            lines.append(f"  {t('prerequisites')}: {', '.join(entry.prerequisites)}")
        if entry.warnings:
            lines.append(f"  {t('warnings_label')}:")
            for w in entry.warnings:
                lines.append(f"    - {w}")
        lines.append(f"  {t('verification')}: {entry.verification} | {t('source')}: {entry.source}")
        return "\n".join(lines)

    def get_relevant_knowledge(self, intent: str, resources: list = None) -> list:
        entries = self.search_by_language(intent, limit=5)
        if not entries and resources:
            for r in resources:
                if r.type == ResourceType.WATER and r.estimated_remaining_hours < 72:
                    entries.extend(self.search_by_language("水 净水 水源 water purify", limit=3))
                elif r.type == ResourceType.FOOD and r.estimated_remaining_hours < 120:
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
