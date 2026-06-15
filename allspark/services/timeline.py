import uuid
from datetime import datetime
from typing import Optional

from allspark.core.i18n import mark, render, t
from allspark.core.models import TimelineEventType


class TimelineManager:
    def __init__(self, db, experience_engine=None):
        self.db = db
        self.experience_engine = experience_engine

    def add_event(self, event_type: str, title: str, description: str = "",
                  emotion: str = "neutral", related_goal_id: str = "",
                  auto: bool = True) -> dict:
        now = datetime.now()
        day = self._get_current_day()
        event_id = f"evt-{uuid.uuid4().hex[:8]}"

        self.db.conn.execute(
            "INSERT OR REPLACE INTO timeline_events VALUES (?,?,?,?,?,?,?,?,?)",
            (
                event_id, day, now.isoformat(), event_type,
                title, description, emotion, related_goal_id,
                1 if auto else 0,
            ),
        )
        self.db.conn.commit()

        return {
            "id": event_id,
            "day": day,
            "timestamp": now.isoformat(),
            "event_type": event_type,
            "title": title,
        }

    def record_goal_completed(self, goal_id: str, goal_title: str):
        return self.add_event(
            event_type=TimelineEventType.GOAL_COMPLETED.value,
            title=mark("timeline_goal_completed", title=goal_title),
            description=mark("timeline_goal_completed_desc", id=goal_id, title=goal_title),
            emotion="positive",
            related_goal_id=goal_id,
        )

    def record_milestone(self, goal_id: str, milestone_desc: str):
        return self.add_event(
            event_type=TimelineEventType.MILESTONE.value,
            title=mark("timeline_milestone", desc=milestone_desc),
            description=milestone_desc,
            emotion="positive",
            related_goal_id=goal_id,
        )

    def record_resource_change(self, resource_type: str, change: str):
        return self.add_event(
            event_type=TimelineEventType.RESOURCE_CHANGE.value,
            title=mark("timeline_resource_change", type=resource_type),
            description=change,
            emotion="neutral",
        )

    def record_member_joined(self, member_name: str):
        return self.add_event(
            event_type=TimelineEventType.MEMBER_JOINED.value,
            title=mark("timeline_member_joined", name=member_name),
            description=mark("timeline_member_joined_desc", name=member_name),
            emotion="positive",
        )

    def record_knowledge_acquired(self, knowledge_title: str):
        return self.add_event(
            event_type=TimelineEventType.KNOWLEDGE_ACQUIRED.value,
            title=mark("timeline_knowledge_acquired", title=knowledge_title),
            description=knowledge_title,
            emotion="positive",
        )

    def record_diary_entry(self, diary_id: str, date: str, emotion: str = "neutral"):
        return self.add_event(
            event_type=TimelineEventType.DIARY_ENTRY.value,
            title=mark("timeline_diary", date=date),
            description=mark("timeline_diary_desc", id=diary_id),
            emotion=emotion,
        )

    def record_system_event(self, title: str, description: str = ""):
        return self.add_event(
            event_type=TimelineEventType.SYSTEM_EVENT.value,
            title=title,
            description=description,
            emotion="neutral",
        )

    def get_timeline(self, day: Optional[int] = None,
                     event_type: Optional[str] = None,
                     limit: int = 50) -> list[dict]:
        query = "SELECT * FROM timeline_events"
        params = []
        conditions = []

        if day is not None:
            conditions.append("day=?")
            params.append(day)
        if event_type:
            conditions.append("event_type=?")
            params.append(event_type)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = self.db.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_day_summary(self, day: int) -> dict:
        rows = self.db.conn.execute(
            "SELECT * FROM timeline_events WHERE day=? ORDER BY timestamp",
            (day,),
        ).fetchall()
        events = [dict(r) for r in rows]

        type_counts = {}
        for e in events:
            et = e["event_type"]
            type_counts[et] = type_counts.get(et, 0) + 1

        return {
            "day": day,
            "event_count": len(events),
            "events": events,
            "type_counts": type_counts,
        }

    def get_all_days(self) -> list[int]:
        rows = self.db.conn.execute(
            "SELECT DISTINCT day FROM timeline_events ORDER BY day DESC"
        ).fetchall()
        return [r[0] for r in rows]

    def format_timeline(self, events: list[dict] = None, limit: int = 20) -> str:
        if events is None:
            events = self.get_timeline(limit=limit)

        if not events:
            return t("timeline_empty")

        lines = [t("timeline_header")]
        current_day = None

        for e in events:
            if e["day"] != current_day:
                current_day = e["day"]
                lines.append(t("timeline_day_header", day=current_day))

            ts = ""
            try:
                dt = datetime.fromisoformat(e["timestamp"])
                ts = dt.strftime("%H:%M")
            except (ValueError, TypeError):
                pass

            emotion_icon = {
                "positive": "😊", "negative": "😔", "neutral": "📝",
            }.get(e.get("emotion", "neutral"), "📝")

            lines.append(f"  {ts} {emotion_icon} {render(e['title'])}")

        return "\n".join(lines)

    def _get_current_day(self) -> int:
        if not self.db:
            return 1
        try:
            row = self.db.conn.execute(
                "SELECT value FROM operating_state WHERE key='timeline_start_at'"
            ).fetchone()
        except Exception:
            row = None

        anchor = None
        if row and row["value"]:
            try:
                anchor = datetime.fromisoformat(row["value"])
            except (ValueError, TypeError):
                anchor = None

        if anchor is None:
            state = self.db.get_operating_state()
            if state.last_mode_change:
                try:
                    anchor = datetime.fromisoformat(state.last_mode_change)
                except (ValueError, TypeError):
                    anchor = None

        if anchor is None:
            anchor = datetime.now()
            try:
                self.db.conn.execute(
                    "INSERT OR REPLACE INTO operating_state VALUES (?,?)",
                    ("timeline_start_at", anchor.isoformat()),
                )
                self.db.conn.commit()
            except Exception:
                pass

        return max(1, (datetime.now() - anchor).days + 1)
