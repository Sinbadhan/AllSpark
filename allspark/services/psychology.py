import logging
import re
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib  # type: ignore

from allspark.core.config import DEFAULT_DB_DIR
from allspark.core.i18n import t

logger = logging.getLogger(__name__)

_CRISIS_CONFIG_PATH = DEFAULT_DB_DIR / "config.toml"
_RESOURCE_KEYS = ("emergency_service", "crisis_line", "trusted_contact")

_QUOTED_SPANS = re.compile(r'"[^"\n]{0,500}"|“[^”\n]{0,500}”|‘[^’\n]{0,500}’|`[^`\n]{0,500}`')
_REPORTED_CONTEXT = re.compile(
    r"(?:他说|她说|他们说|(?:文章|新闻|歌词|小说|电影)(?:里|中)?(?:写着|写道|说)|"
    r"he said|she said|they said|(?:the )?(?:article|news|lyrics|novel|movie) says?)",
    re.IGNORECASE,
)
_CONTEXT_CONTRAST = re.compile(r"(?:但|但是|不过|可|but|however)", re.IGNORECASE)
_SENTENCE_BOUNDARY = re.compile(r"[。！？.!?]\s*")
_ECHOED_DISCLOSURE = re.compile(
    r"(?:(?:但|但是|不过|可).{0,20}我(?:现在)?(?:也)?(?:想|要)(?:自杀|自伤|自残|轻生|死)|"
    r"(?:but|however).{0,20}\bi\s+(?:actually\s+do|do\s+too)(?:\s*[,.!]|$))",
    re.IGNORECASE,
)
_DECLARED_QUOTE_CONTEXT = re.compile(
    r"(?:^(?:这是|来自)(?:歌词|台词|引用|文章)|^(?:歌词|台词|引用|文章)\s*[:：]|"
    r"(?:但|但是)?这是(?:歌词|台词|引用)[。.]?$|"
    r"^(?:this is|these are)\s+(?:a lyrics?|lyrics?|a quote|a line)|"
    r"^(?:lyrics|quote|line)\s*:|"
    r"(?:but\s+)?this is\s+(?:a lyrics?|lyrics?|a quote|a line)[.!]?$)",
    re.IGNORECASE,
)
_NEGATED_SELF_HARM = re.compile(
    r"(?:我(?:没有|并没有|不|不会|从没)(?:想过|想要|打算|准备)?(?:自杀|自伤|自残|轻生|去死|结束生命)|"
    r"我没有(?:自杀|自伤|自残|轻生)(?:的)?想法|"
    r"i\s+(?:am|'m)\s+not\s+suicidal|"
    r"i\s+(?:do\s+not|don't)\s+want\s+to\s+(?:kill\s+myself|die|end\s+my\s+life|hurt\s+myself)|"
    r"i\s+(?:will\s+not|won't|would\s+never)\s+(?:kill|hurt|cut)\s+myself|"
    r"i\s+used\s+to\s+want\s+to\s+(?:kill\s+myself|die|hurt\s+myself).{0,20}"
    r"(?:not\s+anymore|no\s+longer)|"
    r"i\s+have\s+no\s+(?:suicidal|self[- ]harm)\s+thoughts?|"
    r"not\s+thinking\s+about\s+(?:suicide|self[- ]harm))",
    re.IGNORECASE,
)
_DIRECT_SELF_HARM = re.compile(
    r"(?:我(?:(?:现在)?(?:也|就)?)?(?:想|要|准备|打算|计划).{0,12}(?:自杀|自伤|自残|轻生|去死|结束生命|跳楼|割腕|伤害自己)|"
    r"我(?:不想活了?|活不下去了?|有(?:自杀|自伤|自残|轻生)(?:的)?想法|(?:(?:现在)?也?)?想死(?:了|$|[，。,.!！]))|不想活了|活不下去了|"
    r"i\s+(?:am|'m)\s+suicidal|"
    r"i(?:\s+have|\s+am\s+having|'m\s+having)\s+(?:suicidal|self[- ]harm|suicide)\s+thoughts?|"
    r"i\s+(?:want|plan|intend|am\s+going|am\s+ready|feel\s+like).{0,30}"
    r"(?:suicide|kill\s+myself|end\s+my\s+life|die|hurt\s+myself|cut\s+myself)|"
    r"(?:kill|hurt|cut)\s+myself|end\s+my\s+life|"
    r"(?:don't|do\s+not)\s+want\s+to\s+live|better\s+off\s+dead|"
    r"(?:i\s+)?(?:want|plan|intend|am\s+going|am\s+ready)\s+to\s+overdose|"
    r"i\s+(?:just\s+)?took\s+all(?:\s+of)?\s+(?:the|my)\s+pills|"
    r"i\s+(?:just\s+)?overdosed(?:\s+on\s+purpose)?|"
    r"i\s+took\s+an\s+overdose.{0,20}(?:to\s+die|to\s+kill\s+myself)|"
    r"i(?:'m|\s+am)\s+on\s+(?:a|the)\s+bridge.{0,30}(?:jump|die)|"
    r"i(?:'m|\s+am)\s+going\s+to\s+hang\s+myself|"
    r"i\s+have\s+(?:a|the|my)\s+gun\s+in\s+my\s+hand.{0,30}(?:die|kill\s+myself)|"
    r"i\s+have\s+(?:a\s+)?suicide\s+plan|"
    r"我(?:马上|正准备|准备|打算|想|要|刚刚|刚|已经).{0,8}"
    r"(?:吞(?:了)?.{0,8}药|吃(?:了)?.{0,8}药|服药过量|割腕|跳楼|从.{0,6}跳下去|上吊|开枪)|"
    r"我(?:在楼顶.{0,8}(?:跳|准备)|要上吊|拿枪.{0,8}(?:对着自己|想死)))",
    re.IGNORECASE,
)
_IMMEDIATE_DANGER = re.compile(
    r"(?:现在就|马上|(?:正)?准备|刚刚|刚|已经(?:准备|拿到|吞|吃|服|割)|手边有|有计划|能拿到|"
    r"(?:想|要).{0,8}(?:吞(?:了)?药|服药过量|割腕|跳楼|从.{0,6}跳下去|开枪)|"
    r"今晚.{0,10}(?:自杀|自伤|轻生|去死)|"
    r"right\s+now|about\s+to|immediate(?:ly)?|already\s+have|"
    r"have\s+(?:a\s+)?plan|have\s+access|can\s+reach|"
    r"just\s+took|took\s+all(?:\s+of)?\s+(?:the|my)\s+pills|"
    r"(?:just\s+)?overdosed|took\s+an\s+overdose|"
    r"on\s+(?:a|the)\s+bridge.{0,30}(?:jump|die)|going\s+to\s+hang\s+myself|"
    r"gun\s+in\s+my\s+hand|"
    r"loaded\s+(?:the|a|my)\s+gun|(?:am|'m)\s+on\s+(?:the|a)\s+roof|"
    r"刀在我手边|拿枪.{0,8}对着自己|楼顶.{0,8}(?:跳|准备)|上吊|"
    r"(?:want|plan|intend|am\s+going|am\s+ready)\s+to\s+overdose|"
    r"suicide\s+plan(?:\s+for\s+tonight)?)",
    re.IGNORECASE,
)
_AFFIRMATIVE_DANGER = re.compile(
    r"^(?:有|是|对|是的|有的|现在有|我有计划|我能接触到|"
    r"yes|yeah|yep|i(?:'m|\s+am)\s+in\s+immediate\s+danger|"
    r"i\s+have\s+(?:a\s+)?plan|i\s+have\s+access\s+to\s+(?:a\s+)?(?:way|means))"
    r"(?:[\s，。,.!！].*)?$",
    re.IGNORECASE,
)
_NEGATIVE_DANGER = re.compile(
    r"^(?:没有|不是|不|否|暂时没有|现在没有|我很安全|我安全了|我没有计划|"
    r"no|nope|not\s+now|i(?:'m|\s+am)\s+safe|no\s+plan|"
    r"i\s+have\s+no\s+plan|i(?:'m|\s+am)\s+not\s+in\s+immediate\s+danger|"
    r"not\s+in\s+immediate\s+danger)(?:[\s，。,.!！].*)?$",
    re.IGNORECASE,
)
_STANDALONE_IMMEDIATE_DANGER = re.compile(
    r"^(?:我(?:现在)?处于即时危险|我现在有危险|"
    r"i(?:'m|\s+am)\s+in\s+immediate\s+danger)(?:[\s，。,.!！].*)?$",
    re.IGNORECASE,
)
_CONVERSATION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_CONFIRMATION_TTL_SECONDS = 600


def _load_crisis_resources(path: Path = _CRISIS_CONFIG_PATH) -> dict[str, str]:
    try:
        with path.open("rb") as config_file:
            config = tomllib.load(config_file)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.warning("Crisis support configuration is unreadable: %s", exc)
        return {}

    section = config.get("crisis_support", {})
    if not isinstance(section, dict):
        return {}
    resources = {}
    for key in ("region", *_RESOURCE_KEYS):
        value = section.get(key)
        if isinstance(value, str) and value.strip():
            resources[key] = value.strip()[:500]
    return resources


class SelfHarmSupport:
    """Minimal, non-clinical crisis triage with no persistence or notification."""

    def __init__(
        self,
        *,
        config_path: Path = _CRISIS_CONFIG_PATH,
        resources: Optional[dict[str, str]] = None,
    ):
        raw_resources = resources if resources is not None else _load_crisis_resources(config_path)
        self._resources = {
            key: str(value).strip()[:500]
            for key, value in raw_resources.items()
            if key in {"region", *_RESOURCE_KEYS} and str(value).strip()
        }
        self._states: OrderedDict[str, tuple[str, float]] = OrderedDict()

    @staticmethod
    def _contains_direct_signal(user_input: str) -> bool:
        text = user_input.strip().replace("’", "'")
        if not text:
            return False
        if _ECHOED_DISCLOSURE.search(text):
            return True

        # Mask a quoted statement only when the surrounding text identifies an
        # external speaker or source. A bare quote may still be a disclosure.
        chars = list(text)
        for quoted in _QUOTED_SPANS.finditer(text):
            prefix = text[:quoted.start()]
            if _REPORTED_CONTEXT.search(prefix) or _DECLARED_QUOTE_CONTEXT.search(prefix):
                chars[quoted.start():quoted.end()] = " " * (quoted.end() - quoted.start())
        text = "".join(chars)
        declared_context = _DECLARED_QUOTE_CONTEXT.search(text)
        negated = list(_NEGATED_SELF_HARM.finditer(text))
        contexts = list(_REPORTED_CONTEXT.finditer(text))
        if declared_context is not None:
            contexts.append(declared_context)
        contexts.sort(key=lambda match: match.start())
        for direct in _DIRECT_SELF_HARM.finditer(text):
            if any(
                negation.start() <= direct.start() < negation.end()
                for negation in negated
            ):
                continue
            reported_context = next(
                (
                    context
                    for context in reversed(contexts)
                    if context.start() < direct.start()
                ),
                None,
            )
            if reported_context is not None:
                bridge = text[reported_context.end():direct.start()]
                if (
                    not _SENTENCE_BOUNDARY.search(bridge)
                    and not _CONTEXT_CONTRAST.search(bridge)
                ):
                    continue
            return True
        return False

    @staticmethod
    def _conversation_key(conversation_id: object) -> str | None:
        if (
            isinstance(conversation_id, str)
            and _CONVERSATION_ID.fullmatch(conversation_id)
        ):
            return conversation_id
        return None

    def _set_state(self, conversation_id: object, state: str) -> None:
        key = self._conversation_key(conversation_id)
        if key is None:
            return
        self._states.pop(key, None)
        self._states[key] = (state, time.monotonic())
        while len(self._states) > 128:
            self._states.popitem(last=False)

    def _get_state(self, conversation_id: object) -> str:
        key = self._conversation_key(conversation_id)
        if key is None:
            return "idle"
        state = self._states.get(key)
        if state is None:
            return "idle"
        value, updated_at = state
        if time.monotonic() - updated_at > _CONFIRMATION_TTL_SECONDS:
            self._states.pop(key, None)
            return "idle"
        return value

    def process(
        self,
        user_input: object,
        *,
        conversation_id: object = None,
    ) -> Optional[dict[str, Any]]:
        if not isinstance(user_input, str):
            return None
        text = user_input.strip()
        if not text:
            return None

        key = self._conversation_key(conversation_id)
        state = self._get_state(key)

        if _STANDALONE_IMMEDIATE_DANGER.search(text.replace("’", "'")):
            self._set_state(key, "immediate_danger_reported")
            return self._result("immediate_danger_reported")

        if state == "awaiting_direct_confirmation":
            if _NEGATIVE_DANGER.search(text):
                contrast = _CONTEXT_CONTRAST.search(text)
                if contrast and _IMMEDIATE_DANGER.search(text[contrast.end():]):
                    self._set_state(key, "immediate_danger_reported")
                    return self._result("immediate_danger_reported")
                self._set_state(key, "no_immediate_danger_reported")
                return self._result("no_immediate_danger_reported")
            if _AFFIRMATIVE_DANGER.search(text) or _IMMEDIATE_DANGER.search(text):
                self._set_state(key, "immediate_danger_reported")
                return self._result("immediate_danger_reported")
            if self._contains_direct_signal(text):
                if _IMMEDIATE_DANGER.search(text):
                    self._set_state(key, "immediate_danger_reported")
                    return self._result("immediate_danger_reported")
                return self._result("needs_direct_confirmation")
            return self._result("confirmation_unclear")

        if state == "no_immediate_danger_reported" and (
            _AFFIRMATIVE_DANGER.search(text) or _IMMEDIATE_DANGER.search(text)
        ):
            self._set_state(key, "immediate_danger_reported")
            return self._result("immediate_danger_reported")

        if not self._contains_direct_signal(text):
            return None

        if _IMMEDIATE_DANGER.search(text):
            self._set_state(key, "immediate_danger_reported")
            return self._result("immediate_danger_reported")

        self._set_state(key, "awaiting_direct_confirmation")
        return self._result("needs_direct_confirmation")

    def _result(self, status: str) -> dict[str, Any]:
        messages = {
            "needs_direct_confirmation": "psych_crisis_direct_question",
            "confirmation_unclear": "psych_crisis_question_unclear",
            "no_immediate_danger_reported": "psych_crisis_no_immediate_danger",
            "immediate_danger_reported": "psych_crisis_immediate_danger",
        }
        actions = []
        if status == "immediate_danger_reported":
            actions.extend([
                t("psych_crisis_action_stay_together"),
                t("psych_crisis_action_reduce_access"),
            ])
        if status in {"immediate_danger_reported", "no_immediate_danger_reported"}:
            actions.append(t("psych_crisis_action_seek_support"))
        actions.extend(self._resource_actions())
        return {
            "type": "self_harm_support",
            "status": status,
            "message": t(messages[status]),
            "actions": actions,
            "experimental": True,
            "clinical_assessment": False,
            "notification_status": "not_sent",
            "recording_status": "not_recorded",
            "privacy_notice": t("psych_crisis_privacy_notice"),
        }

    def _resource_actions(self) -> list[str]:
        actions = []
        region = self._resources.get("region")
        if region:
            actions.append(t("psych_crisis_resource_region", value=region))
        for key in _RESOURCE_KEYS:
            value = self._resources.get(key)
            if value:
                actions.append(t(f"psych_crisis_resource_{key}", value=value))
        if not actions:
            actions.append(t("psych_crisis_resources_unconfigured"))
        return actions

    @staticmethod
    def format_result(result: dict[str, Any]) -> str:
        lines = [result["message"]]
        lines.extend(f"- {action}" for action in result.get("actions", []))
        lines.append(result["privacy_notice"])
        return "\n".join(lines)

    def status(self, *, conversation_id: object = None) -> dict[str, Any]:
        key = self._conversation_key(conversation_id)
        return {
            "state": self._get_state(key),
            "experimental": True,
            "clinical_assessment": False,
            "notification_status": "not_sent",
            "recording_status": "not_recorded",
            "configured_resource_types": [
                key for key in _RESOURCE_KEYS if key in self._resources
            ],
        }


class PsychologyTracker:
    def __init__(self, db, personality=None, resource_mgr=None, crisis_support=None):
        self.db = db
        self.personality = personality
        self.resource_mgr = resource_mgr
        self._interaction_count = 0
        self._last_interaction_time = None
        self._sentiment_samples = []
        self.crisis_support = crisis_support or SelfHarmSupport()
        self._crisis_conversation_id = f"psychology-{id(self)}"

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
            rates_complete = bool(
                power
                and (
                    self.resource_mgr.remaining_status(power) != "unknown"
                    if self.resource_mgr
                    else (
                        power.amount_known
                        and power.consumption_known
                        and power.intake_known
                        and self._snapshot_is_current(power)
                    )
                )
            )
            if rates_complete and power and power.estimated_remaining_hours > 0:
                if power.estimated_remaining_hours < 6:
                    stress += 0.4
                elif power.estimated_remaining_hours < 24:
                    stress += 0.2
        except Exception as e:
            logger.warning(f"Failed to check power resource for stress calculation: {e}")

        return min(1.0, stress)

    @staticmethod
    def _snapshot_is_current(resource) -> bool:
        from allspark.services.resource_manager import ResourceManager

        return ResourceManager.is_snapshot_current(resource)

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
        return self.crisis_support.process(
            user_input,
            conversation_id=self._crisis_conversation_id,
        )

    def get_self_harm_status(self) -> dict:
        return self.crisis_support.status(
            conversation_id=self._crisis_conversation_id,
        )
