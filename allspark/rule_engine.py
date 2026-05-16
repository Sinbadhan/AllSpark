from allspark.database import Database
from allspark.models import KnowledgeEntry
from allspark.knowledge_engine import KnowledgeEngine
from allspark.resource_manager import ResourceManager
from allspark.survival_engine import SurvivalAssessmentEngine
from allspark.i18n import t
from allspark.mission_planner import MissionPlanner
from allspark.personality import PersonalitySystem
from allspark.map_system import MapSystem
from allspark.models import OperatingMode
from allspark.hardware import detect_hardware, compute_feature_flags, FeatureFlags
from allspark.module_loader import ModuleRegistry
from allspark.llm_engine import LLMEngine
from allspark.experience_engine import ExperienceEngine


class RuleEngine:
    def __init__(self, db: Database, flags: FeatureFlags = None):
        self.db = db
        self.resource_mgr = ResourceManager(db)
        self.personality = PersonalitySystem()
        self.maps = MapSystem(db)

        if flags is None:
            registry_loaded = ModuleRegistry.load_from_db(db)
            if registry_loaded:
                self.flags = registry_loaded.flags
                self.registry = registry_loaded
            else:
                profile = detect_hardware()
                self.flags = compute_feature_flags(profile.tier, profile.gpu_available)
                self.registry = ModuleRegistry(self.flags)
        else:
            self.flags = flags
            self.registry = ModuleRegistry(flags)

        self.knowledge = None
        self.survival = None
        self.planner = None
        self.llm = LLMEngine(self.flags)
        self.experience = ExperienceEngine(db, llm=self.llm)

    def initialize(self):
        self.resource_mgr.init_defaults()

        if self.registry.should_load("knowledge_fts"):
            self.knowledge = KnowledgeEngine(self.db)
            self.registry.register("knowledge_fts", self.knowledge)
            self._load_knowledge()

        self.survival = SurvivalAssessmentEngine(self.db, self.resource_mgr)
        self.planner = MissionPlanner(self.db, self.resource_mgr)

        self.registry.register("rule_engine", self)
        self.registry.register("text_interaction", self)
        self.registry.register("spark_network", self)

        if self.flags.multilingual_knowledge:
            self.registry.register("multilingual", True)

        if self.flags.self_learning:
            self.registry.register("self_learning", True)

        if self.flags.offline_map:
            self.registry.register("offline_map", self.maps)

        if self.flags.llm:
            loaded = self.llm.load()
            if loaded:
                self.registry.register("llm", self.llm)

        if self.flags.self_learning:
            self.registry.register("self_learning", self.experience)

        if self.registry.should_load("governance"):
            from allspark.governance import GovernanceEngine
            self.governance = GovernanceEngine(db=self.db, llm_engine=self.llm)
            self.registry.register("governance", self.governance)

        if self.registry.should_load("trade_engine"):
            from allspark.trade_engine import TradeEngine
            network = self.registry.get("spark_network")
            verifier = self.registry.get("knowledge_verifier")
            self.trade = TradeEngine(db=self.db, network=network, verifier=verifier)
            self.registry.register("trade_engine", self.trade)

        if self.registry.should_load("power_monitor"):
            from allspark.power_monitor import PowerMonitor
            self.power_monitor = PowerMonitor(db=self.db)
            self.registry.register("power_monitor", self.power_monitor)

        if self.registry.should_load("sensor_hub"):
            from allspark.sensor_hub import SensorHub
            self.sensor_hub = SensorHub(db=self.db)
            self.registry.register("sensor_hub", self.sensor_hub)

        if self.registry.should_load("data_preservation"):
            from allspark.data_preservation import DataPreservation
            self.data_preservation = DataPreservation(db=self.db)
            self.registry.register("data_preservation", self.data_preservation)
            integrity = self.data_preservation.startup_integrity_check()
            if integrity.get("warnings"):
                import logging
                logging.getLogger(__name__).warning(
                    f"Startup integrity check: {integrity['warnings']}"
                )

        if self.registry.should_load("boot_manager"):
            from allspark.boot_manager import BootManager
            self.boot_manager = BootManager(db=self.db)
            self.registry.register("boot_manager", self.boot_manager)

        if self.registry.should_load("goal_engine"):
            from allspark.goal_engine import GoalEngine
            self.goal_engine = GoalEngine(
                db=self.db, resource_mgr=self.resource_mgr,
                survival=self.survival,
            )
            self.registry.register("goal_engine", self.goal_engine)

        if self.registry.should_load("reset_manager"):
            from allspark.reset_manager import ResetManager
            self.reset_manager = ResetManager(
                db=self.db, data_preservation=self.data_preservation,
                resource_mgr=self.resource_mgr,
            )
            self.registry.register("reset_manager", self.reset_manager)

        if self.registry.should_load("daily_briefing"):
            from allspark.daily_briefing import DailyBriefing
            self.daily_briefing = DailyBriefing(
                db=self.db, resource_mgr=self.resource_mgr,
                survival=self.survival,
                goal_engine=getattr(self, 'goal_engine', None),
                personality=getattr(self, 'personality', None),
            )
            self.registry.register("daily_briefing", self.daily_briefing)

        if self.registry.should_load("timeline"):
            from allspark.timeline import TimelineManager
            self.timeline = TimelineManager(
                db=self.db,
                experience_engine=getattr(self, 'experience', None),
            )
            self.registry.register("timeline", self.timeline)

        if self.registry.should_load("diary"):
            from allspark.diary import DiaryManager
            self.diary = DiaryManager(
                db=self.db,
                timeline=getattr(self, 'timeline', None),
            )
            self.registry.register("diary", self.diary)

        if self.registry.should_load("weather"):
            from allspark.weather import WeatherPredictor
            self.weather = WeatherPredictor(
                db=self.db,
                sensor_hub=getattr(self, 'sensor_hub', None),
            )
            self.registry.register("weather", self.weather)

        if self.registry.should_load("psychology"):
            from allspark.psychology import PsychologyTracker
            self.psychology = PsychologyTracker(
                db=self.db,
                personality=getattr(self, 'personality', None),
            )
            self.registry.register("psychology", self.psychology)

        if self.registry.should_load("gps_manager"):
            from allspark.gps_manager import GPSManager
            self.gps_manager = GPSManager(
                db=self.db,
                sensor_hub=getattr(self, 'sensor_hub', None),
            )
            self.registry.register("gps_manager", self.gps_manager)

        if self.registry.should_load("environment"):
            from allspark.environment import EnvironmentAssessor
            self.environment = EnvironmentAssessor(
                db=self.db,
                weather=getattr(self, 'weather', None),
                resource_mgr=self.resource_mgr,
                survival=self.survival,
            )
            self.registry.register("environment", self.environment)

        if self.registry.should_load("voice"):
            from allspark.voice import VoiceManager
            self.voice = VoiceManager(
                db=self.db,
                diary=getattr(self, 'diary', None),
                llm_engine=getattr(self, 'llm', None),
            )
            self.registry.register("voice", self.voice)

        self.registry.save_to_db(self.db)
        self._assessment_cache = None
        self._assessment_cache_time = 0
        self._assessment_cache_ttl = 60

    def _load_knowledge(self):
        from allspark.knowledge_data import get_tier0_knowledge
        from allspark.knowledge_data_en import get_tier0_knowledge_en
        from allspark.knowledge_data_tier12 import get_tier1_knowledge, get_tier2_knowledge
        for entry in get_tier0_knowledge():
            existing = self.db.get_knowledge(entry.id)
            if existing is None:
                self.db.save_knowledge(entry)
        for entry in get_tier0_knowledge_en():
            existing = self.db.get_knowledge(entry.id)
            if existing is None:
                self.db.save_knowledge(entry)
        for entry in get_tier1_knowledge():
            existing = self.db.get_knowledge(entry.id)
            if existing is None:
                self.db.save_knowledge(entry)
        for entry in get_tier2_knowledge():
            existing = self.db.get_knowledge(entry.id)
            if existing is None:
                self.db.save_knowledge(entry)

    def _refresh_assessment(self, force: bool = False) -> dict:
        import time as _time
        now = _time.time()
        if not force and self._assessment_cache and (now - self._assessment_cache_time) < self._assessment_cache_ttl:
            return self._assessment_cache

        mode, _ = self.resource_mgr.update_operating_mode()
        warnings = self.resource_mgr.check_warnings()
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
                    "知识库模块未加载，无法查询知识。当前硬件可能不支持全文检索。",
                    add_greeting=True
                )
        else:
            return self._handle_general(user_input, resources, warnings, phase)

    def _handle_status(self, assessment: dict, mode: OperatingMode,
                       warnings: list) -> str:
        lines = [
            self.survival.get_assessment_summary(),
            "",
            self.resource_mgr.get_resource_summary(),
            "",
            self.planner.format_tasks(assessment["active_tasks"] or self.planner.suggest_tasks(assessment["resources"])),
        ]
        if warnings:
            lines.append("")
            lines.append("🚨 行动建议：")
            for w in warnings:
                if w["level"] == "critical":
                    lines.append(f"  🚨 {w['resource']}：立即采取行动！")
                else:
                    lines.append(f"  ⚡ {w['resource']}：请尽快补充")
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
            "── 基础 ──",
            f"  {t('help_status')}",
            f"  {t('help_resource')}",
            f"  {t('help_water')}",
            f"  {t('help_fire')}",
            f"  {t('help_food')}",
            f"  {t('help_shelter')}",
            f"  {t('help_medical')}",
            f"  {t('help_map')}",
            "  map add <名> <类型>        — 添加地图 POI",
            "  map remove <id>            — 移除地图 POI",
            f"  {t('help_set')}",
            f"  {t('help_task')}",
            "",
            "── 知识与经验 ──",
            "  知识 <关键词>               — 搜索知识库",
            "  经验 log <事件> <结果>      — 记录经验",
            "  经验 patterns              — 查看经验模式",
            "  经验 recent                — 最近经验",
            "",
            "── AI 与模型 ──",
            "  llm / llm load             — 查看/加载 LLM 模型",
            "  llm chat <消息>            — 与 LLM 对话",
            "",
            "── 知识包与验证 ──",
            "  skf export <路径>          — 导出 SKF 知识包",
            "  skf import <路径>          — 导入 SKF 知识包",
            "  skf info <路径>            — 查看 SKF 信息",
            "  验证 <ID>                  — 验证知识条目",
            "  验证 all / unverified      — 批量验证",
            "",
            "── 通信与图像 ──",
            "  网络 scan / start / stop   — 火种通信",
            "  网络 exchange <节点>       — 请求知识交换",
            "  识别 <图片路径>            — 图像分析",
            "  识别 plant/wound/hazard    — 指定识别类型",
            "",
            "── 社区治理 ──",
            "  社区 add <名字> [角色]     — 添加成员",
            "  社区 list / assess         — 成员列表/组织评估",
            "  社区 value <ID>            — 生存价值评估",
            "  社区 conflict <标题> <方>  — 创建冲突记录",
            "  社区 mediate <ID>          — AI 调解冲突",
            "  交易 propose/accept/eval   — 知识交易",
            "",
            "── 硬件与数据 ──",
            "  电力 status / start / stop — 电力监控",
            "  电力 input <Wh>            — 手动输入电量",
            "  传感器 list / detect       — 传感器管理",
            "  传感器 snapshot            — 环境快照",
            "  固化 start / stop          — 自动保存",
            "  固化 snapshot / emergency  — 快照/紧急保存",
            "",
            "── 系统 ──",
            f"  {t('help_lang')}",
            "  模块 / module               — 查看模块状态",
            "  模块 enable <名>            — 启用模块",
            "  模块 disable <名>           — 禁用模块",
            "",
            "── 目标与重置 ──",
            "  目标 / goals                — 查看目标清单",
            "  目标 添加 <标题>            — 添加手动目标",
            "  目标 完成/放弃/暂停/恢复 <ID> — 目标操作",
            "  目标 里程碑 <ID>            — 查看目标里程碑",
            "  目标 自动生成               — 根据状态生成目标",
            "  重置 评估/档案/出厂         — 三级重置",
            "",
            "── 生存体验 ──",
            "  简报 / briefing             — 今日生存简报",
            "  时间线 / timeline           — 生存时间线",
            "  时间线 day <N>              — 查看第N天事件",
            "  日记 写 / diary add         — 写日记",
            "  日记 查看/删除/情绪         — 日记管理",
            "  天气 / weather              — 天气预测",
            "  天气 气压 <hPa>             — 输入气压数据",
            "  天气 云图                   — 云图识别指南",
            "  心理 / psychology           — 心理状态",
            "  心理 评估                   — 心理自评问卷",
            "",
            "── 感知与语音 ──",
            "  定位 / gps                  — 当前位置",
            "  定位 set <纬度> <经度>      — 手动设置位置",
            "  定位 轨迹/记录/距离         — 轨迹管理",
            "  环境 / env                  — 环境评估",
            "  语音 load [模型]            — 加载语音模型",
            "  语音 识别 [文件]            — 语音转文字",
            "  语音 说话 <文本>            — 语音合成",
            "  语音 日记                   — 语音日记",
            "",
            f"  {t('help_help')}",
        ]
        return "\n".join(help_lines)

    def _handle_knowledge_query(self, intent: str, resources: list,
                                 warnings: list) -> str:
        intent_map = {
            "water": "水 净水 水源 饮水",
            "fire": "火 生火 点火 取暖 燃料",
            "food": "食物 可食用 狩猎 捕鱼 觅食",
            "shelter": "庇护所 避难所 遮蔽 帐篷 搭建",
            "medical": "急救 医疗 伤口 止血 CPR 受伤",
            "navigation": "导航 指南针 方向 星象 地图",
        }
        query = intent_map.get(intent, intent)
        entries = self.knowledge.get_relevant_knowledge(query, resources)

        if not entries:
            fallback = self.knowledge.search(intent, limit=5)
            if fallback:
                entries = fallback

        if not entries:
            return self.personality.format_response(
                f"知识库中暂无关于「{intent}」的条目。\n"
                "你可以尝试其他关键词，或使用 '帮助' 查看所有可用命令。",
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

        if self.llm.available:
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

        responses = {
            0: "当前处于紧急生存阶段。请告诉我你最重要的需求：水、火、食物、庇护或医疗？",
            1: "当前处于短期生存阶段。请描述你的具体需求，我会从知识库中寻找相关建议。",
            2: "当前处于中期自给阶段。你想了解农业、工具制造还是能源方面的知识？",
            3: "当前处于生活质量阶段。我可以帮你了解医疗、通信或制造方面的知识。",
            4: "当前处于文明复兴阶段。我们可以讨论教育、技术或社区治理等话题。",
        }
        return self.personality.format_response(
            f"我暂时无法理解你的问题。\n{responses.get(phase, responses[1])}\n"
            "输入 '帮助' 查看可用命令。",
            add_greeting=True
        )
