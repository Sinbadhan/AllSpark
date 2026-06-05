import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from allspark.core.i18n import t

logger = logging.getLogger(__name__)


class DiaryManager:
    def __init__(self, db, timeline=None):
        self.db = db
        self.timeline = timeline

    def add_entry(self, content: str, emotion: str = "neutral",
                  keywords: list[str] = None, related_goal_id: str = "",
                  is_public: bool = False) -> dict:
        now = datetime.now()
        entry_id = f"diary-{uuid.uuid4().hex[:8]}"
        date_str = now.strftime("%Y-%m-%d")

        self.db.conn.execute(
            "INSERT OR REPLACE INTO diary_entries VALUES (?,?,?,?,?,?,?,?,?)",
            (
                entry_id,
                date_str,
                content,
                emotion,
                json.dumps(keywords or [], ensure_ascii=False),
                related_goal_id,
                "",
                1 if is_public else 0,
                now.isoformat(),
            ),
        )
        self.db.conn.commit()

        if self.timeline:
            self.timeline.record_diary_entry(
                diary_id=entry_id,
                date=date_str,
                emotion=emotion,
            )

        return {
            "id": entry_id,
            "date": date_str,
            "emotion": emotion,
            "content_length": len(content),
        }

    def get_entries(self, date: Optional[str] = None,
                    emotion: Optional[str] = None,
                    limit: int = 50) -> list[dict]:
        query = "SELECT * FROM diary_entries"
        params = []
        conditions = []

        if date:
            conditions.append("date=?")
            params.append(date)
        if emotion:
            conditions.append("emotion=?")
            params.append(emotion)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = self.db.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_entry(self, entry_id: str) -> Optional[dict]:
        row = self.db.conn.execute(
            "SELECT * FROM diary_entries WHERE id=?", (entry_id,)
        ).fetchone()
        return dict(row) if row else None

    def delete_entry(self, entry_id: str) -> bool:
        row = self.get_entry(entry_id)
        if not row:
            return False
        self.db.conn.execute("DELETE FROM diary_entries WHERE id=?", (entry_id,))
        self.db.conn.commit()
        return True

    def get_dates(self) -> list[str]:
        rows = self.db.conn.execute(
            "SELECT DISTINCT date FROM diary_entries ORDER BY date DESC"
        ).fetchall()
        return [r[0] for r in rows]

    def get_emotion_stats(self) -> dict:
        rows = self.db.conn.execute(
            "SELECT emotion, COUNT(*) as cnt FROM diary_entries GROUP BY emotion"
        ).fetchall()
        stats = {r["emotion"]: r["cnt"] for r in rows}
        total = sum(stats.values())
        return {
            "total_entries": total,
            "positive": stats.get("positive", 0),
            "neutral": stats.get("neutral", 0),
            "negative": stats.get("negative", 0),
            "positive_ratio": stats.get("positive", 0) / total if total > 0 else 0,
        }

    def format_entries(self, entries: list[dict] = None, limit: int = 10) -> str:
        if entries is None:
            entries = self.get_entries(limit=limit)

        if not entries:
            return t("diary_empty")

        lines = [t("diary_header")]
        for e in entries:
            emotion_icon = {
                "positive": "😊", "neutral": "📝", "negative": "😔",
            }.get(e.get("emotion", "neutral"), "📝")

            content_preview = e["content"][:80]
            if len(e["content"]) > 80:
                content_preview += "..."
            lines.append(f"  {emotion_icon} [{e['date']}] {content_preview}")

        return "\n".join(lines)

    def format_entry_detail(self, entry: dict) -> str:
        emotion_icon = {
            "positive": "😊", "neutral": "📝", "negative": "😔",
        }.get(entry.get("emotion", "neutral"), "📝")

        lines = [
            t("diary_detail_title", date=entry['date']),
            t("diary_emotion", icon=emotion_icon, emotion=entry['emotion']),
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            entry["content"],
        ]

        keywords = entry.get("keywords", "[]")
        try:
            kw_list = json.loads(keywords) if isinstance(keywords, str) else keywords
            if kw_list:
                lines.append(t("diary_keywords", keywords=", ".join(kw_list)))
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"Failed to parse diary keywords: {e}")

        return "\n".join(lines)
