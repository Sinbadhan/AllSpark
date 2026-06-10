import logging
from datetime import datetime

from allspark.core.i18n import t
from allspark.core.models import ResourceType

logger = logging.getLogger(__name__)

_SURVIVAL_KNOWLEDGE_MAP = {
    ResourceType.POWER: ["power", "energy", "electricity", "solar", "battery"],
    ResourceType.WATER: ["water", "purification", "hydration", "rain"],
    ResourceType.FOOD: ["food", "foraging", "hunting", "agriculture", "edible"],
    ResourceType.FIRE: ["fire", "warmth", "cooking", "shelter"],
    ResourceType.STORAGE: ["storage", "preservation", "shelter"],
}

_PHASE_KNOWLEDGE_PRIORITY = {
    0: ["water", "fire", "shelter", "first-aid"],
    1: ["food", "foraging", "water", "purification"],
    2: ["agriculture", "preservation", "tool-making"],
    3: ["construction", "communication", "navigation"],
    4: ["civilization", "governance", "education"],
}


class DailyBriefing:
    def __init__(self, db, resource_mgr=None, survival=None,
                 goal_engine=None, personality=None):
        self.db = db
        self.resource_mgr = resource_mgr
        self.survival = survival
        self.goal_engine = goal_engine
        self.personality = personality

    def generate(self) -> str:
        now = datetime.now()
        sections = []

        sections.append(self._header(now))
        sections.append(self._resource_section())
        sections.append(self._warning_section())
        sections.append(self._goal_section())
        sections.append(self._task_section())
        sections.append(self._knowledge_tip())
        sections.append(self._footer(now))

        return "\n\n".join(s for s in sections if s)

    def _header(self, now: datetime) -> str:
        date_str = now.strftime("%Y-%m-%d %H:%M")
        day_num = self._calculate_day_number()
        return (
            f"{t('briefing_title', date=date_str)}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{t('briefing_day', day=day_num)}"
        )

    def _calculate_day_number(self) -> int:
        state = self.db.get_operating_state()
        if state.last_mode_change:
            try:
                first = datetime.fromisoformat(state.last_mode_change)
                return max(1, (datetime.now() - first).days + 1)
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to parse last_mode_change date: {e}")
        return 1

    def _resource_section(self) -> str:
        resources = self.db.get_all_resources()
        if not resources:
            return t("briefing_not_configured")

        lines = [t("resource_title")]
        icons = {
            ResourceType.POWER: "⚡", ResourceType.WATER: "💧",
            ResourceType.FOOD: "🍞", ResourceType.FIRE: "🔥",
            ResourceType.STORAGE: "💾",
        }

        for r in resources:
            icon = icons.get(r.type, "📦")
            is_offline = r.current_amount == 0 and r.daily_consumption == 0
            res_name = t(f"resource_{r.type.value}")

            if is_offline:
                lines.append(f"  {icon} {res_name}: [dim]{t('resource_offline')}[/]")
                continue

            remaining = ""
            if r.estimated_remaining_hours > 0:
                hours = r.estimated_remaining_hours
                if hours < 24:
                    remaining = f" ({hours:.0f}h)"
                else:
                    remaining = f" ({hours/24:.1f}d)"

            status = ""
            if r.current_amount == 0:
                status = " ⚠️"
            elif r.estimated_remaining_hours > 0 and r.estimated_remaining_hours < 24:
                status = " ⚡"

            lines.append(
                f"  {icon} {res_name}: {r.current_amount:.1f}{r.unit}{remaining}{status}"
            )

        return "\n".join(lines)

    def _warning_section(self) -> str:
        warnings = []
        if self.resource_mgr:
            warnings = self.resource_mgr.check_warnings()

        if not warnings:
            return ""

        lines = [t("advice_title")]
        for w in warnings[:5]:
            level_icon = "🚨" if w["level"] == "critical" else "⚡"
            lines.append(f"  {level_icon} {w['message']}")
        return "\n".join(lines)

    def _goal_section(self) -> str:
        if not self.goal_engine:
            return ""

        goals = self.db.get_active_goals()
        if not goals:
            return t("no_active_goals")

        lines = [t("briefing_active_goals")]
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_goals = sorted(goals, key=lambda g: priority_order.get(g.priority, 99))

        for g in sorted_goals[:5]:
            icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(
                g.priority, "⚪"
            )
            pct = int(g.progress * 100)
            lines.append(f"  {icon} {g.title} ({pct}%)")

        return "\n".join(lines)

    def _task_section(self) -> str:
        active = self.db.get_active_tasks()
        if not active:
            return ""

        lines = [t("briefing_urgent_tasks")]
        for task in active[:5]:
            status_icon = {"pending": "⬜", "in_progress": "🔄"}.get(task.status, "⬜")
            lines.append(f"  {status_icon} {task.title}")
        return "\n".join(lines)

    def _knowledge_tip(self) -> str:
        count = self.db.get_knowledge_count()
        if count == 0:
            return ""

        target_categories = self._get_relevant_categories()
        entry = self._pick_knowledge_entry(target_categories)
        if not entry:
            return ""

        return (
            f"{t('briefing_daily_knowledge')}\n"
            f"  [{entry.category}] {entry.title}\n"
            f"  {entry.summary}"
        )

    def _get_relevant_categories(self) -> list[str]:
        priority_cats = []

        if self.survival:
            phase = self.survival.assess().get("phase", 0)
            phase_cats = _PHASE_KNOWLEDGE_PRIORITY.get(phase, [])
            priority_cats.extend(phase_cats)

        if self.resource_mgr:
            warnings = self.resource_mgr.check_warnings()
            for w in warnings:
                res_name = w.get("resource", "").lower()
                for rtype, keywords in _SURVIVAL_KNOWLEDGE_MAP.items():
                    res_label = t(f"resource_{rtype.value}").lower()
                    if res_name in res_label or res_label in res_name:
                        priority_cats.extend(keywords)

        resources = self.db.get_all_resources()
        for r in resources:
            if r.current_amount == 0 and r.daily_consumption == 0:
                keywords = _SURVIVAL_KNOWLEDGE_MAP.get(r.type, [])
                priority_cats.extend(keywords)

        seen = set()
        unique = []
        for c in priority_cats:
            if c not in seen:
                seen.add(c)
                unique.append(c)
        return unique

    def _pick_knowledge_entry(self, target_categories: list[str]):
        import random

        all_cats = self.db.get_distinct_knowledge_categories()
        if not all_cats:
            return None

        for cat_keyword in target_categories:
            for cat in all_cats:
                if cat_keyword.lower() in cat.lower():
                    entries = self.db.get_knowledge_by_category(cat)
                    if entries:
                        return random.choice(entries)

        subcats = []
        try:
            rows = self.db.conn.execute(
                "SELECT DISTINCT subcategory FROM knowledge WHERE subcategory != ''"
            ).fetchall()
            subcats = [r["subcategory"] for r in rows]
        except Exception as e:
            logger.warning(f"Failed to query distinct subcategories: {e}")

        for cat_keyword in target_categories:
            for sub in subcats:
                if cat_keyword.lower() in sub.lower():
                    rows = self.db.conn.execute(
                        "SELECT * FROM knowledge WHERE subcategory = ?", (sub,)
                    ).fetchall()
                    if rows:
                        entries = [self.db._row_to_entry(r) for r in rows]
                        return random.choice(entries)

        cat = random.choice(all_cats)
        entries = self.db.get_knowledge_by_category(cat)
        if entries:
            return random.choice(entries)

        return None

    def _footer(self, now: datetime) -> str:
        state = self.db.get_operating_state()
        mode = state.mode
        mode_names = {
            "proactive": t("mode_proactive"),
            "standard": t("mode_standard"),
            "economy": t("mode_economy"),
            "hibernation": t("mode_hibernation"),
            "recovery": t("mode_recovery"),
        }
        mode_label = mode_names.get(mode, mode)
        return (
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{t('briefing_footer', mode=mode_label)}"
        )

    def generate_short(self) -> str:
        """Condensed briefing: resource status + critical warnings only."""
        now = datetime.now()
        sections = []

        # Header (single line)
        day_num = self._calculate_day_number()
        sections.append(f"{t('briefing_title', date=now.strftime('%Y-%m-%d %H:%M'))} | {t('briefing_day', day=day_num)}")

        # Resources — compact single-line per resource
        resources = self.db.get_all_resources()
        if resources:
            icons = {
                ResourceType.POWER: "⚡", ResourceType.WATER: "💧",
                ResourceType.FOOD: "🍞", ResourceType.FIRE: "🔥",
                ResourceType.STORAGE: "💾",
            }
            parts = []
            for r in resources:
                icon = icons.get(r.type, "📦")
                is_offline = r.current_amount == 0 and r.daily_consumption == 0
                if is_offline:
                    continue
                res_name = t(f"resource_{r.type.value}")
                remaining = ""
                if r.estimated_remaining_hours > 0:
                    hours = r.estimated_remaining_hours
                    remaining = f"({hours / 24:.1f}d)" if hours >= 24 else f"({hours:.0f}h)"
                parts.append(f"{icon}{res_name}:{r.current_amount:.0f}{r.unit}{remaining}")
            if parts:
                sections.append(" ".join(parts))
            else:
                sections.append(t("briefing_not_configured"))

        # Critical warnings only
        if self.resource_mgr:
            warnings = self.resource_mgr.check_warnings()
            critical = [w for w in warnings if w.get("level") == "critical"]
            if critical:
                lines = [t("warning_critical")]
                for w in critical[:3]:
                    lines.append(f"  🚨 {w['message']}")
                sections.append("\n".join(lines))

        return "\n".join(s for s in sections if s)

    def save_briefing_to_timeline(self):
        now = datetime.now()
        day = self._calculate_day_number()
        content = self.generate()

        self.db.conn.execute(
            "INSERT OR REPLACE INTO timeline_events VALUES (?,?,?,?,?,?,?,?,?)",
            (
                f"briefing-{now.strftime('%Y%m%d')}",
                day,
                now.isoformat(),
                "system_event",
                t("briefing_title", date=now.strftime("%Y-%m-%d")),
                content[:500],
                "neutral",
                "",
                1,
            ),
        )
        self.db.conn.commit()
