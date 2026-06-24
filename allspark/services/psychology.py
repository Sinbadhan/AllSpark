import logging
from datetime import datetime
from typing import Any, Optional

from allspark.core.i18n import mark, t

logger = logging.getLogger(__name__)

# Self-harm intervention levels (PRD §8.2)
_INTERVENTION_LEVELS = {
    1: {"type": "gentle_reminder"},
    2: {"type": "escalation"},
    3: {"type": "critical_alert"},
}

_SELF_HARM_KEYWORDS_ZH = ["自杀", "不想活", "结束生命", "活不下去", "去死", "跳楼", "割腕"]
_SELF_HARM_KEYWORDS_EN = ["suicide", "kill myself", "end my life", "don't want to live", "better off dead"]


class PsychologyTracker:
    def __init__(self, db, personality=None):
        self.db = db
        self.personality = personality
        self._interaction_count = 0
        self._last_interaction_time = None
        self._sentiment_samples = []
        self._self_harm_level = 0
        self._self_harm_triggers = 0

    def record_interaction(self, sentiment: str = "neutral"):
        self._interaction_count += 1
        self._last_interaction_time = datetime.now()
        self._sentiment_samples.append({
            "time": datetime.now().isoformat(),
            "sentiment": sentiment,
        })
        if len(self._sentiment_samples) > 100:
            self._sentiment_samples = self._sentiment_samples[-100:]

    def assess_state(self) -> dict:
        result: dict[str, Any] = {
            "loneliness_index": self._calculate_loneliness(),
            "stress_index": self._calculate_stress(),
            "overall_state": "stable",
            "needs_intervention": False,
            "intervention_type": None,
            "recommendations": [],
        }

        if result["loneliness_index"] > 0.7:
            result["overall_state"] = "lonely"
            result["needs_intervention"] = True
            result["intervention_type"] = "companion"
            result["recommendations"].append(t("psych_lonely_advice"))

        if result["stress_index"] > 0.7:
            if result["overall_state"] == "lonely":
                result["overall_state"] = "distressed"
            else:
                result["overall_state"] = "stressed"
            result["needs_intervention"] = True
            if result["intervention_type"] is None:
                result["intervention_type"] = "calm"
            result["recommendations"].append(t("psych_stress_advice"))

        recent_sentiments = [s["sentiment"] for s in self._sentiment_samples[-10:]]
        negative_ratio = sum(1 for s in recent_sentiments if s == "negative") / max(len(recent_sentiments), 1)
        if negative_ratio > 0.6:
            result["needs_intervention"] = True
            if result["intervention_type"] is None:
                result["intervention_type"] = "emotional_support"
            result["recommendations"].append(t("psych_negative_advice"))

        return result

    def _calculate_loneliness(self) -> float:
        if not self._last_interaction_time:
            return 0.8

        hours_since = (datetime.now() - self._last_interaction_time).total_seconds() / 3600

        if hours_since < 1:
            return 0.1
        elif hours_since < 6:
            return 0.3
        elif hours_since < 24:
            return 0.5
        elif hours_since < 72:
            return 0.7
        else:
            return 0.9

    def _calculate_stress(self) -> float:
        stress = 0.0

        state = self.db.get_operating_state()
        if state.mode in ("economy", "hibernation"):
            stress += 0.3

        try:
            from allspark.core.models import ResourceType

            power = self.db.get_resource(ResourceType.POWER)
            if power and power.estimated_remaining_hours > 0:
                if power.estimated_remaining_hours < 6:
                    stress += 0.4
                elif power.estimated_remaining_hours < 24:
                    stress += 0.2
        except Exception as e:
            logger.warning(f"Failed to check power resource for stress calculation: {e}")

        return min(1.0, stress)

    def get_self_assessment_questions(self) -> list[dict]:
        return [
            {
                "id": "sleep",
                "question": t("psych_q_sleep"),
                "options": [t("psych_opt_sleep_good"), t("psych_opt_sleep_fair"), t("psych_opt_sleep_poor")],
                "scores": [0.0, 0.3, 0.7],
            },
            {
                "id": "appetite",
                "question": t("psych_q_appetite"),
                "options": [t("psych_opt_appetite_normal"), t("psych_opt_appetite_slight"), t("psych_opt_appetite_severe")],
                "scores": [0.0, 0.2, 0.5],
            },
            {
                "id": "mood",
                "question": t("psych_q_mood"),
                "options": [t("psych_opt_mood_calm"), t("psych_opt_mood_anxious"), t("psych_opt_mood_low")],
                "scores": [0.0, 0.4, 0.8],
            },
            {
                "id": "social",
                "question": t("psych_q_lonely"),
                "options": [t("psych_opt_lonely_no"), t("psych_opt_lonely_sometimes"), t("psych_opt_lonely_often")],
                "scores": [0.0, 0.3, 0.7],
            },
            {
                "id": "hope",
                "question": t("psych_q_hope"),
                "options": [t("psych_opt_hope_yes"), t("psych_opt_hope_unsure"), t("psych_opt_hope_no")],
                "scores": [0.0, 0.3, 0.8],
            },
        ]

    def process_assessment(self, answers: dict[str, int]) -> dict:
        questions = self.get_self_assessment_questions()
        total_score = 0.0
        max_score = 0.0

        for q in questions:
            idx = answers.get(q["id"], 0)
            idx = min(idx, len(q["scores"]) - 1)
            total_score += q["scores"][idx]
            max_score += max(q["scores"])

        normalized = total_score / max_score if max_score > 0 else 0

        if normalized < 0.2:
            state_label = t("psych_state_good")
            advice = t("psych_advice_good")
        elif normalized < 0.4:
            state_label = t("psych_state_mild")
            advice = t("psych_advice_mild")
        elif normalized < 0.6:
            state_label = t("psych_state_moderate")
            advice = t("psych_advice_moderate")
        else:
            state_label = t("psych_state_severe")
            advice = t("psych_advice_severe")

        return {
            "score": round(normalized, 2),
            "state": state_label,
            "advice": advice,
            "needs_intervention": normalized >= 0.6,
        }

    def format_status(self) -> str:
        assessment = self.assess_state()
        loneliness_pct = int(assessment["loneliness_index"] * 100)
        stress_pct = int(assessment["stress_index"] * 100)

        state_icons = {
            "stable": "✅", "lonely": "😔", "stressed": "😰",
            "distressed": "🚨",
        }
        icon = state_icons.get(assessment["overall_state"], "📝")

        lines = [
            t("psych_status_header"),
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            t("psych_overall_state", icon=icon, state=t(f"psych_{assessment['overall_state']}")),
            t("psych_loneliness_index", pct=loneliness_pct),
            t("psych_stress_index", pct=stress_pct),
            t("psych_needs_intervention", yes=t("field_yes") if assessment['needs_intervention'] else t("field_no")),
        ]

        if assessment["recommendations"]:
            lines.append("")
            for r in assessment["recommendations"]:
                lines.append(f"  💡 {r}")

        return "\n".join(lines)

    def check_and_trigger_intervention(self) -> Optional[dict]:
        assessment = self.assess_state()
        if not assessment["needs_intervention"]:
            return None

        intervention = assessment["intervention_type"]

        if intervention == "companion":
            return {
                "type": "companion_mode",
                "message": t("psych_intervention_companion"),
                "suggested_actions": [t("diary_cmd"), t("chat_cmd"), t("briefing_cmd")],
            }

        if intervention == "calm":
            return {
                "type": "stress_relief",
                "message": t("psych_intervention_calm"),
                "suggested_actions": [t("diary_cmd"), t("goals_cmd"), t("psych_assess_cmd")],
            }

        if intervention == "emotional_support":
            return {
                "type": "emotional_support",
                "message": t("psych_intervention_support"),
                "suggested_actions": [t("diary_cmd"), t("psych_assess_cmd"), t("weather_cmd")],
            }

        return None

    def detect_self_harm_risk(self, user_input: str) -> Optional[dict]:
        text = user_input.lower()
        detected = any(kw in text for kw in _SELF_HARM_KEYWORDS_ZH + _SELF_HARM_KEYWORDS_EN)

        if not detected:
            if self._self_harm_level > 0 and self._self_harm_triggers == 0:
                self._self_harm_level = max(0, self._self_harm_level - 1)
            return None

        self._self_harm_triggers += 1

        if self._self_harm_level < 3:
            self._self_harm_level += 1

        level = self._self_harm_level
        level_info = _INTERVENTION_LEVELS[level]

        message_keys = {
            1: "psych_selfharm_l1",
            2: "psych_selfharm_l2",
            3: "psych_selfharm_l3",
        }
        message = t(message_keys.get(level, "psych_selfharm_l1"))

        result = {
            "type": "self_harm_intervention",
            "level": level,
            "intervention_type": level_info["type"],
            "message": message,
            "triggers": self._self_harm_triggers,
        }

        if level >= 3:
            result["notify_authority"] = True
            result["recorded"] = True

            try:
                from allspark.core.models import TimelineEvent
                event = TimelineEvent(
                    id=f"intervention-{datetime.now().strftime('%H%M%S')}",
                    day=0,
                    timestamp=datetime.now().isoformat(),
                    event_type="system",
                    title=mark("timeline_selfharm_intervention"),
                    description=mark("timeline_selfharm_intervention_desc"),
                    emotion="critical",
                    related_goal_id="",
                    auto_generated=True,
                )
                self.db.save_timeline_event(event)
            except Exception as e:
                logger.warning(f"Failed to record self-harm Level 3 intervention to timeline: {e}")

        return result

    def get_self_harm_status(self) -> dict:
        return {
            "current_level": self._self_harm_level,
            "total_triggers": self._self_harm_triggers,
            "max_level": 3,
        }
