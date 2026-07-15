import logging
import re

from allspark.container import ServiceContainer
from allspark.core.i18n import t
from allspark.core.models import OperatingMode, ResourceType
from allspark.core.tokenizer import tokenize
from allspark.services.psychology import SelfHarmSupport
from allspark.services.system_health import assess_system_health

logger = logging.getLogger(__name__)

INTENT_KEYWORDS = {
    "water": ["水", "渴", "喝水", "净水", "水源", "找水", "饮水", "water", "thirst"],
    "fire": ["火", "生火", "点火", "取暖", "取暖", "燃烧", "fire", "warm", "点燃"],
    "food": ["食物", "吃", "饿", "觅食", "可食用", "有毒", "植物", "狩猎", "捕鱼", "food", "hunger", "hungry"],
    "shelter": ["庇护所", "住", "帐篷", "避难", "遮蔽", "房屋", "shelter", "camp"],
    "medical": ["伤", "血", "急救", "病", "疼痛", "发烧", "感染", "CPR", "止血", "medical", "hurt", "injury"],
    "navigation": ["方向", "导航", "指南针", "地图", "星", "位置", "navigation", "compass", "map"],
    "resource": ["资源", "物资", "储备", "存量", "resource"],
    "status": ["状态", "情况", "怎么样", "汇报", "status"],
    "help": ["帮助", "怎么用", "你能做什么", "help"],
}


class RuleEngine:
    def __init__(self, container: ServiceContainer):
        self.container = container
        self.db = container.db
        self.resource_mgr = container.require("resource_manager")
        self.personality = container.require("personality")
        self.maps = container.get("map_system")
        self.knowledge = container.get("knowledge")
        self.survival = container.get("survival_engine")
        self.planner = container.get("mission_planner")
        self.llm = container.get("llm")
        self.crisis_support = container.get("crisis_support") or SelfHarmSupport()
        self.action_loop = container.get("action_loop")
        self._assessment_cache: dict | None = None
        self._assessment_cache_time = 0.0
        self._assessment_cache_ttl = 60

    def _refresh_assessment(self, force: bool = False) -> dict:
        import time as _time
        now = _time.time()
        if not force and self._assessment_cache and (now - self._assessment_cache_time) < self._assessment_cache_ttl:
            return self._assessment_cache

        mode, _ = self.resource_mgr.update_operating_mode()
        warnings = self.resource_mgr.check_warnings()
        assert self.survival is not None
        assessment = self.survival.assess()
        phase = assessment["phase"]
        resources = assessment["resources"]

        self._assessment_cache = {
            "mode": mode,
            "warnings": warnings,
            "assessment": assessment,
            "phase": phase,
            "resources": resources,
        }
        self._assessment_cache_time = now
        return self._assessment_cache

    def process_input(
        self,
        user_input: str,
        *,
        conversation_id: str | None = None,
    ) -> str:
        return self.process_input_result(
            user_input,
            conversation_id=conversation_id,
        )["response"]

    def process_input_result(
        self,
        user_input: str,
        *,
        conversation_id: str | None = None,
    ) -> dict:
        safety_response = self.process_safety_input(
            user_input,
            conversation_id=conversation_id,
        )
        if safety_response is not None:
            return {"response": safety_response, "safety": True}

        if self.action_loop is not None:
            interaction = self.action_loop.process_chat(
                user_input,
                conversation_id=conversation_id,
            )
            if interaction is not None:
                if interaction.metadata.get("state_changed"):
                    self._assessment_cache = None
                return {
                    "response": interaction.response,
                    "interaction": interaction.metadata,
                }

        intent = self.personality.classify_intent(user_input)
        needs_fresh = intent in ("status", "resource")
        cached = self._refresh_assessment(force=needs_fresh)
        mode = cached["mode"]
        warnings = cached["warnings"]
        assessment = cached["assessment"]
        phase = cached["phase"]
        resources = cached["resources"]

        self.personality.determine_mode(mode, warnings, phase)

        if intent == "status":
            response = self._handle_status(assessment, mode, warnings)
        elif intent == "resource":
            response = self._handle_resources()
        elif intent == "help":
            response = self._handle_help()
        elif intent in ("water", "fire", "food", "shelter", "medical", "navigation"):
            if self.knowledge:
                response = self._handle_knowledge_query(
                    user_input, intent, resources, warnings
                )
            else:
                response = self._format_trusted_response(
                    t("knowledge_module_not_loaded"),
                    "none",
                )
        else:
            response = self._handle_general(user_input, resources, warnings, phase)
        return {"response": response}

    def process_safety_input(
        self,
        user_input: str,
        *,
        conversation_id: str | None = None,
    ) -> str | None:
        result = self.crisis_support.process(
            user_input,
            conversation_id=conversation_id,
        )
        if result is None:
            return None
        return self.crisis_support.format_result(result)

    def _handle_status(self, assessment: dict, mode: OperatingMode,
                       warnings: list) -> str:
        assert self.survival is not None
        assert self.planner is not None
        lines = [
            self.survival.get_assessment_summary(),
            "",
            self.resource_mgr.get_resource_summary(),
            "",
            self.planner.format_tasks(
                assessment["active_tasks"]
                or self.planner.suggest_tasks(
                    assessment["resources"],
                    phase=assessment["phase"],
                    stale_fields=assessment["stale_fields"],
                )
            ),
        ]
        if warnings:
            lines.append("")
            lines.append(t("action_suggestions"))
            for w in warnings:
                if w["level"] == "critical":
                    lines.append(f"  🚨 {w['resource']}：{t('action_immediate')}")
                else:
                    lines.append(f"  ⚡ {w['resource']}：{t('action_soon')}")
        return self.personality.format_response("\n".join(lines), add_greeting=True)

    def _handle_resources(self) -> str:
        return self.personality.format_response(
            self.resource_mgr.get_resource_summary(), add_greeting=True
        )

    def _handle_help(self) -> str:
        help_lines = [
            t("help_title"),
            "",
            t("help_commands"),
            "",
            t("help_section_basic"),
            f"  {t('help_status')}",
            f"  {t('help_resource')}",
            f"  {t('help_water')}",
            f"  {t('help_fire')}",
            f"  {t('help_food')}",
            f"  {t('help_shelter')}",
            f"  {t('help_medical')}",
            f"  {t('help_map')}",
            f"  {t('help_map_add')}",
            f"  {t('help_map_remove')}",
            f"  {t('help_set')}",
            f"  {t('help_task')}",
            "",
            t("help_section_knowledge"),
            f"  {t('help_knowledge_search')}",
            f"  {t('help_exp_log')}",
            f"  {t('help_exp_patterns')}",
            f"  {t('help_exp_recent')}",
            "",
            t("help_section_ai"),
            f"  {t('help_llm_load')}",
            f"  {t('help_llm_chat')}",
            "",
            t("help_section_skf"),
            f"  {t('help_skf_export')}",
            f"  {t('help_skf_import')}",
            f"  {t('help_skf_info')}",
            f"  {t('help_verify')}",
            f"  {t('help_verify_batch')}",
            "",
            t("help_section_comms"),
            f"  {t('help_network')}",
            f"  {t('help_network_exchange')}",
            f"  {t('help_vision')}",
            f"  {t('help_vision_type')}",
            "",
            t("help_section_governance"),
            f"  {t('help_community_add')}",
            f"  {t('help_community_list')}",
            f"  {t('help_community_value')}",
            f"  {t('help_community_conflict')}",
            f"  {t('help_community_mediate')}",
            f"  {t('help_trade')}",
            "",
            t("help_section_hardware"),
            f"  {t('help_power')}",
            f"  {t('help_power_input')}",
            f"  {t('help_sensor')}",
            f"  {t('help_sensor_snapshot')}",
            f"  {t('help_preserve')}",
            f"  {t('help_preserve_emergency')}",
            "",
            t("help_section_system"),
            f"  {t('help_lang')}",
            f"  {t('help_module')}",
            f"  {t('help_module_enable')}",
            f"  {t('help_module_disable')}",
            "",
            t("help_section_goals"),
            f"  {t('help_goals')}",
            f"  {t('help_goal_add')}",
            f"  {t('help_goal_ops')}",
            f"  {t('help_goal_milestone')}",
            f"  {t('help_goal_auto')}",
            f"  {t('help_reset')}",
            "",
            t("help_section_survival"),
            f"  {t('help_briefing')}",
            f"  {t('help_timeline')}",
            f"  {t('help_timeline_day')}",
            f"  {t('help_diary')}",
            f"  {t('help_diary_ops')}",
            f"  {t('help_weather')}",
            f"  {t('help_weather_pressure')}",
            f"  {t('help_weather_cloud')}",
            f"  {t('help_psychology')}",
            f"  {t('help_psychology_assess')}",
            "",
            t("help_section_perception"),
            f"  {t('help_gps')}",
            f"  {t('help_gps_set')}",
            f"  {t('help_gps_track')}",
            f"  {t('help_env')}",
            f"  {t('help_voice_load')}",
            f"  {t('help_voice_recognize')}",
            f"  {t('help_voice_speak')}",
            f"  {t('help_voice_diary')}",
            "",
            f"  {t('help_help')}",
        ]
        return "\n".join(help_lines)

    def _handle_knowledge_query(self, user_input: str, intent: str, resources: list,
                                 warnings: list) -> str:
        assert self.knowledge is not None
        intent_map = {
            "water": t("intent_keywords_water"),
            "fire": t("intent_keywords_fire"),
            "food": t("intent_keywords_food"),
            "shelter": t("intent_keywords_shelter"),
            "medical": t("intent_keywords_medical"),
            "navigation": t("intent_keywords_navigation"),
        }
        expansion_query = intent_map.get(intent, intent)
        direct = self.knowledge.search_by_language(user_input, limit=5)
        decision = self._direct_query_decision(
            user_input, direct[0] if direct else None
        )
        if decision == "miss":
            return self._format_trusted_response(
                t("no_knowledge_match"),
                "none",
            )

        expanded = self.knowledge.get_relevant_knowledge(expansion_query, resources)
        if decision == "specific":
            entries = self._merge_entries(direct, expanded)
        else:
            entries = self._merge_entries(expanded, direct)

        if not entries:
            return self._format_trusted_response(
                t("no_knowledge_match"), "none"
            )

        lines = []
        if warnings:
            for w in warnings:
                if w["level"] == "critical":
                    lines.append(f"🚨 {w['message']}")
        if lines:
            lines.append("")
        # SHA-150: 1 main answer + 2 related links (not full-text concat).
        lines.append(self.knowledge.format_answer(entries[:3]))

        return self._format_trusted_response(
            "\n".join(lines),
            "specific" if decision == "specific" else "general",
        )

    def _format_trusted_response(self, content: str, match: str) -> str:
        health = assess_system_health(self.container)["state"]
        resources = self._resource_trust_state(
            self.resource_mgr.check_warnings()
        )
        trust_line = t(
            "answer_trust_line",
            system=t(f"answer_system_{health}"),
            resources=t(f"answer_resources_{resources}"),
            match=t(f"answer_match_{match}"),
        )
        return self.personality.format_response(
            f"{trust_line}\n\n{content}", add_greeting=True
        )

    def _resource_trust_state(self, warnings: list) -> str:
        if any(warning.get("level") == "critical" for warning in warnings):
            return "critical"
        if warnings:
            return "warning"
        required = (
            ResourceType.POWER,
            ResourceType.WATER,
            ResourceType.FOOD,
        )
        resources = [self.db.get_resource(resource_type) for resource_type in required]
        if any(
            resource is None or not self.resource_mgr.is_configured(resource)
            for resource in resources
        ):
            return "unknown"
        return "ready"

    @staticmethod
    def _merge_entries(primary: list, secondary: list) -> list:
        seen = set()
        merged = []
        for entry in [*primary, *secondary]:
            if entry.id not in seen:
                seen.add(entry.id)
                merged.append(entry)
        return merged[:10]

    @staticmethod
    def _direct_query_decision(user_input: str, top_entry) -> str:
        """Return specific, generic, or miss for rule-knowledge orchestration."""
        stop_terms = {
            "如何", "怎么", "怎样", "什么", "怎么办", "方法", "请问",
            "可以", "能否", "哪里", "哪些",
            "how", "what", "when", "where", "why", "to", "a", "an",
            "the", "with", "using", "use",
        }
        query_terms = RuleEngine._compact_terms(
            term.lower()
            for term in tokenize(user_input).split()
            if len(term) >= 2 and term.lower() not in stop_terms
        )
        object_terms = RuleEngine._explicit_object_terms(user_input)

        if not top_entry:
            return "miss" if object_terms else "generic"

        content = " ".join(
            [
                top_entry.title,
                top_entry.summary,
                *top_entry.steps,
                *top_entry.prerequisites,
                *top_entry.warnings,
                top_entry.category,
                top_entry.subcategory,
            ]
        ).lower()
        if any(term not in content for term in object_terms):
            return "miss"
        title = top_entry.title.lower()
        title_matches = sum(term in title for term in query_terms)
        return "specific" if object_terms or title_matches >= 2 else "generic"

    @staticmethod
    def _explicit_object_terms(user_input: str) -> list[str]:
        lowered = user_input.lower()
        terms = re.findall(
            r"(?:使用|用)([a-z0-9\u4e00-\u9fff-]{1,24}?)"
            r"(?:来|去|进行|取火|生火|点火|净水|过滤|搭建|止血|$)",
            lowered,
        )
        terms.extend(
            re.findall(
                r"(?:with|using)\s+(?:(?:a|an|the)\s+)?([a-z0-9-]+)",
                lowered,
            )
        )
        return RuleEngine._compact_terms(term for term in terms if len(term) >= 2)

    @staticmethod
    def _compact_terms(terms) -> list[str]:
        unique = list(dict.fromkeys(terms))
        return [
            term
            for term in unique
            if not any(term != other and term in other for other in unique)
        ]

    def _handle_general(self, user_input: str, resources: list,
                        warnings: list, phase: int | None) -> str:
        context_parts = []
        if warnings:
            for w in warnings:
                context_parts.append(f"[Alert] {w['message']}")
        if resources:
            for r in resources[:5]:
                if self.resource_mgr.remaining_status(r) == "unknown":
                    continue
                remaining = (
                    "sustained"
                    if self.resource_mgr.remaining_status(r) == "sustained"
                    else f"~{r.estimated_remaining_hours}h left"
                )
                context_parts.append(
                    f"[{r.type.value}] {r.current_amount}{r.unit}, {remaining}"
                )

        context = "\n".join(context_parts) if context_parts else ""

        if self.llm and self.llm.available:
            llm_response = self.llm.survival_chat(user_input, context=context, phase=phase)
            if llm_response:
                return self._format_trusted_response(
                    llm_response, "unverified"
                )

        if self.knowledge:
            entries = self.knowledge.search(user_input, limit=3)
            if entries:
                # SHA-150: 1 main answer + 2 related links (not full-text concat).
                return self._format_trusted_response(
                    self.knowledge.format_answer(entries), "general"
                )

        return self._format_trusted_response(
            t(
                "general_fallback",
                phase_suggestion=t(
                    f"phase_fallback_{phase}"
                    if phase is not None
                    else "phase_fallback_unknown"
                ),
            ),
            "none",
        )
