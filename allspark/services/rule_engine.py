import logging

from allspark.container import ServiceContainer
from allspark.core.i18n import t
from allspark.core.models import OperatingMode

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
        self._assessment_cache = None
        self._assessment_cache_time = 0
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

    def process_input(self, user_input: str) -> str:
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
            return self._handle_status(assessment, mode, warnings)
        elif intent == "resource":
            return self._handle_resources()
        elif intent == "help":
            return self._handle_help()
        elif intent in ("water", "fire", "food", "shelter", "medical", "navigation"):
            if self.knowledge:
                return self._handle_knowledge_query(intent, resources, warnings)
            else:
                return self.personality.format_response(
                    t("knowledge_module_not_loaded"),
                    add_greeting=True
                )
        else:
            return self._handle_general(user_input, resources, warnings, phase)

    def _handle_status(self, assessment: dict, mode: OperatingMode,
                       warnings: list) -> str:
        assert self.survival is not None
        assert self.planner is not None
        lines = [
            self.survival.get_assessment_summary(),
            "",
            self.resource_mgr.get_resource_summary(),
            "",
            self.planner.format_tasks(assessment["active_tasks"] or self.planner.suggest_tasks(assessment["resources"])),
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

    def _handle_knowledge_query(self, intent: str, resources: list,
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
        query = intent_map.get(intent, intent)
        entries = self.knowledge.get_relevant_knowledge(query, resources)

        if not entries:
            fallback = self.knowledge.search(intent, limit=5)
            if fallback:
                entries = fallback

        if not entries:
            return self.personality.format_response(
                t("no_knowledge", topic=intent),
                add_greeting=True
            )

        lines = []
        if warnings:
            for w in warnings:
                if w["level"] == "critical":
                    lines.append(f"🚨 {w['message']}")

        for entry in entries:
            lines.append("")
            lines.append(self.knowledge.format_entry(entry))

        return self.personality.format_response("\n".join(lines), add_greeting=True)

    def _handle_general(self, user_input: str, resources: list,
                        warnings: list, phase: int) -> str:
        context_parts = []
        if warnings:
            for w in warnings:
                context_parts.append(f"[Alert] {w['message']}")
        if resources:
            for r in resources[:5]:
                context_parts.append(f"[{r.type.value}] {r.current_amount}{r.unit}, ~{r.estimated_remaining_hours}h left")

        context = "\n".join(context_parts) if context_parts else ""

        if self.llm and self.llm.available:
            llm_response = self.llm.survival_chat(user_input, context=context, phase=phase)
            if llm_response:
                return self.personality.format_response(llm_response, add_greeting=True)

        if self.knowledge:
            entries = self.knowledge.search(user_input, limit=3)
            if entries:
                lines = []
                for entry in entries:
                    lines.append(self.knowledge.format_entry(entry))
                    lines.append("")
                return self.personality.format_response("\n".join(lines), add_greeting=True)

        return self.personality.format_response(
            t("general_fallback", phase_suggestion=t(f"phase_fallback_{phase}")),
            add_greeting=True
        )
