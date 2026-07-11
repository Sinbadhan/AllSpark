import logging

from allspark.core.database import Database
from allspark.core.i18n import get_language, t
from allspark.core.models import ResourceType

logger = logging.getLogger(__name__)


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
                lines.append(f"  • [{e.id}] {e.title}")
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
