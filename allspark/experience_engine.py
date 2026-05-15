import re
import uuid
from datetime import datetime
from typing import Optional

from allspark.database import Database
from allspark.models import ExperienceLog, KnowledgeEntry
from allspark.i18n import get_language
from allspark.tokenizer import tokenize


class ExperienceEngine:
    def __init__(self, db: Database, llm=None):
        self.db = db
        self.llm = llm
        self._pattern_cache: dict[str, int] = {}
        self._load_patterns()

    def _load_patterns(self):
        rows = self.db.conn.execute(
            "SELECT event, COUNT(*) as cnt FROM experience_log GROUP BY event HAVING cnt > 1"
        ).fetchall()
        for r in rows:
            self._pattern_cache[r["event"]] = r["cnt"]

    def log(self, event: str, outcome: str, lesson: str = "",
            related_knowledge_id: str = "") -> ExperienceLog:
        entry = ExperienceLog(
            id=str(uuid.uuid4())[:8],
            timestamp=datetime.now().isoformat(),
            event=event,
            outcome=outcome,
            lesson=lesson,
            related_knowledge_id=related_knowledge_id,
        )
        self.db.save_experience(entry)

        self._pattern_cache[event] = self._pattern_cache.get(event, 0) + 1

        if self._pattern_cache[event] >= 3 and not related_knowledge_id:
            self._try_promote_to_knowledge(event)

        return entry

    def _try_promote_to_knowledge(self, event: str):
        rows = self.db.conn.execute(
            "SELECT * FROM experience_log WHERE event=? ORDER BY timestamp DESC LIMIT 5",
            (event,)
        ).fetchall()

        if len(rows) < 3:
            return

        outcomes = [r["outcome"] for r in rows]
        lessons = [r["lesson"] for r in rows if r["lesson"]]

        if self.llm and self.llm.available:
            kid = self._llm_promote(event, outcomes, lessons)
            if kid:
                for r in rows:
                    self.db.conn.execute(
                        "UPDATE experience_log SET related_knowledge_id=? WHERE id=?",
                        (kid, r["id"])
                    )
                self.db.conn.commit()
                return

        kid = self._rule_promote(event, outcomes, lessons)
        if kid:
            for r in rows:
                self.db.conn.execute(
                    "UPDATE experience_log SET related_knowledge_id=? WHERE id=?",
                    (kid, r["id"])
                )
            self.db.conn.commit()

    def _rule_promote(self, event: str, outcomes: list[str],
                      lessons: list[str]) -> Optional[str]:
        category = self._classify_event(event)
        kid = f"experience/{category}/{event.replace(' ', '_')[:40]}"

        summary_parts = [f"Based on {len(outcomes)} experiences: {event}"]
        if lessons:
            summary_parts.append("Lessons: " + "; ".join(lessons[:3]))

        steps = [f"Observed outcome: {o}" for o in outcomes[:5]]
        warnings = []
        if any("fail" in o.lower() or "失败" in o for o in outcomes):
            warnings.append("Some attempts failed - verify before relying on this")

        entry = KnowledgeEntry(
            id=kid,
            category=category,
            subcategory="experience",
            priority=2,
            title=f"[Experience] {event}",
            summary=" ".join(summary_parts),
            steps=steps,
            prerequisites=[],
            warnings=warnings,
            verification="experience_based",
            source="self_learned",
            version=1,
            language="zh" if any('\u4e00' <= c <= '\u9fff' for c in event) else "en",
        )
        self.db.save_knowledge(entry)
        return kid

    def _llm_promote(self, event: str, outcomes: list[str],
                     lessons: list[str]) -> Optional[str]:
        prompt = (
            f"Based on the following survival experiences, create a concise knowledge entry.\n"
            f"Event: {event}\n"
            f"Outcomes: {'; '.join(outcomes[:5])}\n"
            f"Lessons: {'; '.join(lessons[:3]) if lessons else 'None'}\n\n"
            f"Output format (strict):\n"
            f"TITLE: <short title>\n"
            f"SUMMARY: <1-2 sentence summary>\n"
            f"STEPS: <numbered steps, one per line>\n"
            f"WARNINGS: <warnings if any>"
        )
        response = self.llm.generate(prompt, max_tokens=256, temperature=0.3)
        if not response or "[LLM error" in response:
            return None

        try:
            title = self._extract_field(response, "TITLE") or event
            summary = self._extract_field(response, "SUMMARY") or ""
            steps_text = self._extract_field(response, "STEPS") or ""
            warnings_text = self._extract_field(response, "WARNINGS") or ""

            steps = [s.strip().lstrip("0123456789. ") for s in steps_text.split("\n") if s.strip()]
            warnings = [w.strip().lstrip("- ") for w in warnings_text.split("\n") if w.strip()]

            category = self._classify_event(event)
            kid = f"experience/{category}/{event.replace(' ', '_')[:40]}"

            entry = KnowledgeEntry(
                id=kid,
                category=category,
                subcategory="experience",
                priority=2,
                title=f"[Experience] {title}",
                summary=summary,
                steps=steps,
                prerequisites=[],
                warnings=warnings,
                verification="experience_based",
                source="self_learned_llm",
                version=1,
                language="zh" if any('\u4e00' <= c <= '\u9fff' for c in event) else "en",
            )
            self.db.save_knowledge(entry)
            return kid
        except Exception:
            return None

    def _extract_field(self, text: str, field: str) -> Optional[str]:
        pattern = rf"{field}:\s*(.+?)(?=\n[A-Z]+:|$)"
        m = re.search(pattern, text, re.DOTALL)
        return m.group(1).strip() if m else None

    def _classify_event(self, event: str) -> str:
        keywords_map = {
            "water": ["水", "water", "饮水", "净水", "河流", "rain"],
            "food": ["食物", "food", "采集", "狩猎", "种植", "harvest"],
            "fire": ["火", "fire", "生火", "取暖", "燃烧"],
            "shelter": ["庇护", "shelter", "搭建", "帐篷", "避难"],
            "medical": ["伤", "医疗", "medical", "感染", "急救", "wound"],
            "navigation": ["方向", "导航", "navigation", "地图", "路"],
            "craft": ["制作", "craft", "工具", "编织", "建造"],
            "agriculture": ["种植", "农业", "agriculture", "作物", "土壤"],
            "energy": ["电", "能源", "energy", "发电", "太阳能"],
        }
        event_lower = event.lower()
        for cat, keywords in keywords_map.items():
            for kw in keywords:
                if kw in event_lower:
                    return cat
        return "general"

    def get_patterns(self) -> list[dict]:
        patterns = []
        for event, count in sorted(self._pattern_cache.items(), key=lambda x: -x[1]):
            if count >= 2:
                promoted = self.db.conn.execute(
                    "SELECT related_knowledge_id FROM experience_log WHERE event=? AND related_knowledge_id != '' LIMIT 1",
                    (event,)
                ).fetchone()
                patterns.append({
                    "event": event,
                    "count": count,
                    "promoted": bool(promoted and promoted["related_knowledge_id"]),
                    "knowledge_id": promoted["related_knowledge_id"] if promoted else None,
                })
        return patterns

    def get_recent(self, limit: int = 20) -> list[ExperienceLog]:
        return self.db.get_recent_experiences(limit)

    def get_stats(self) -> dict:
        total = self.db.conn.execute("SELECT COUNT(*) FROM experience_log").fetchone()[0]
        promoted = self.db.conn.execute(
            "SELECT COUNT(DISTINCT related_knowledge_id) FROM experience_log WHERE related_knowledge_id != ''"
        ).fetchone()[0]
        patterns = len([c for c in self._pattern_cache.values() if c >= 2])
        return {
            "total_experiences": total,
            "patterns_detected": patterns,
            "knowledge_promoted": promoted,
        }
