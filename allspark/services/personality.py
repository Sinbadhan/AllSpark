import logging
from datetime import datetime

from allspark.core.config import PERSONALITY_GREETING_KEYS, PERSONALITY_TEMPLATES
from allspark.core.i18n import mark, t
from allspark.core.models import OperatingMode, PersonalityMode
from allspark.services.rule_engine import INTENT_KEYWORDS

logger = logging.getLogger(__name__)


class PersonalitySystem:
    def __init__(self, db=None):
        self.current_mode = PersonalityMode.STABLE
        self.db = db
        self._mode_history: list[dict] = []

    def determine_mode(self, operating_mode: OperatingMode,
                       warnings: list, phase: int | None,
                       is_multiplayer: bool = False) -> PersonalityMode:
        previous_mode = self.current_mode
        has_critical = any(w.get("level") == "critical" for w in warnings)

        if operating_mode == OperatingMode.HIBERNATION or has_critical or phase == 0:
            self.current_mode = PersonalityMode.CRISIS
        elif is_multiplayer:
            self.current_mode = PersonalityMode.MULTIPLAYER
        elif operating_mode in (OperatingMode.STANDARD, OperatingMode.ECONOMY):
            if warnings:
                self.current_mode = PersonalityMode.CRISIS
            elif phase is not None and phase >= 4:
                self.current_mode = PersonalityMode.RENAISSANCE
            else:
                self.current_mode = PersonalityMode.STABLE
        else:
            if phase is not None and phase >= 4:
                self.current_mode = PersonalityMode.RENAISSANCE
            else:
                self.current_mode = PersonalityMode.COMPANION

        # Record mode transitions for evolution tracking
        if self.current_mode != previous_mode:
            self._record_transition(previous_mode, self.current_mode, operating_mode, phase)

        return self.current_mode

    def _record_transition(self, from_mode: PersonalityMode, to_mode: PersonalityMode,
                           operating_mode: OperatingMode, phase: int | None):
        entry = {
            "from": from_mode.value,
            "to": to_mode.value,
            "operating_mode": operating_mode.value,
            "phase": phase,
            "timestamp": datetime.now().isoformat(),
        }
        self._mode_history.append(entry)
        if len(self._mode_history) > 200:
            self._mode_history = self._mode_history[-200:]

        if self.db:
            try:
                from allspark.core.models import TimelineEvent
                event = TimelineEvent(
                    id=f"personality-{datetime.now().strftime('%H%M%S')}",
                    day=0,
                    timestamp=datetime.now().isoformat(),
                    event_type="system",
                    title=mark("timeline_personality_change", from_mode=from_mode.value, to_mode=to_mode.value),
                    description=mark("timeline_personality_change_desc", operating_mode=operating_mode.value, phase=str(phase)),
                    emotion="neutral",
                    related_goal_id="",
                    auto_generated=True,
                )
                self.db.save_timeline_event(event)
            except Exception as e:
                logger.warning(f"Failed to record personality transition to timeline: {e}")

    def get_evolution_stats(self) -> dict:
        """Get personality mode transition statistics."""
        if not self._mode_history:
            return {"total_transitions": 0, "modes": {}}

        mode_counts: dict[str, int] = {}
        for entry in self._mode_history:
            mode = entry["to"]
            mode_counts[mode] = mode_counts.get(mode, 0) + 1

        return {
            "total_transitions": len(self._mode_history),
            "current_mode": self.current_mode.value,
            "modes": mode_counts,
            "last_transition": self._mode_history[-1] if self._mode_history else None,
        }

    def get_template(self) -> dict:
        return PERSONALITY_TEMPLATES.get(self.current_mode.value, PERSONALITY_TEMPLATES["stable"])

    def set_mode(self, mode):
        """Force the personality into a specific mode (e.g. after crisis escalation).

        Accepts either a PersonalityMode enum or its string value.
        """
        if isinstance(mode, PersonalityMode):
            target = mode
        else:
            try:
                target = PersonalityMode(str(mode))
            except ValueError:
                logger.warning("PersonalitySystem.set_mode: unknown mode '%s'", mode)
                return self.current_mode
        if target != self.current_mode:
            self._record_transition(self.current_mode, target, OperatingMode.STANDARD, 0)
            self.current_mode = target
        return self.current_mode

    def _get_greeting(self) -> str:
        key = PERSONALITY_GREETING_KEYS.get(self.current_mode.value, "greeting_stable")
        return t(key)

    def greet(self) -> str:
        tmpl = self.get_template()
        return f"{tmpl['emoji_prefix']} {self._get_greeting()}"

    def format_response(self, content: str, add_greeting: bool = False) -> str:
        tmpl = self.get_template()
        parts = []
        if add_greeting:
            parts.append(f"{tmpl['emoji_prefix']} {self._get_greeting()}")
        parts.append(content)
        if self.current_mode == PersonalityMode.CRISIS:
            parts.append(f"\n{t('crisis_mode_notice')}")
        return "\n".join(parts)

    def classify_intent(self, user_input: str) -> str:
        text = user_input.lower()
        best_intent = "general"
        best_count = 0
        for intent, keywords in INTENT_KEYWORDS.items():
            count = sum(1 for kw in keywords if kw in text)
            if count > best_count:
                best_count = count
                best_intent = intent
        return best_intent
