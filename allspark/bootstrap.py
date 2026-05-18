import logging

from allspark.container import ServiceContainer
from allspark.database import Database
from allspark.hardware import detect_hardware, compute_feature_flags, FeatureFlags, DeployMode, DEPLOY_MODE_MAP
from allspark.module_loader import ModuleRegistry
from allspark.resource_manager import ResourceManager
from allspark.knowledge_engine import KnowledgeEngine
from allspark.survival_engine import SurvivalAssessmentEngine
from allspark.mission_planner import MissionPlanner
from allspark.personality import PersonalitySystem
from allspark.map_system import MapSystem
from allspark.llm_engine import LLMEngine
from allspark.experience_engine import ExperienceEngine
from allspark.i18n import t

logger = logging.getLogger(__name__)


class ApplicationBootstrap:
    def __init__(self, db: Database, flags: FeatureFlags = None):
        self.db = db
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

        self.container = ServiceContainer(db=db, flags=self.flags)

    def bootstrap(self) -> ServiceContainer:
        self._register_core_services()
        self._init_resources()
        self._load_knowledge()
        self._register_conditional_services()
        self._init_docker()
        self.registry.save_to_db(self.db)
        return self.container

    def _register_core_services(self):
        self.container.register("flags", self.flags)
        self.container.register("registry", self.registry)

        resource_mgr = ResourceManager(self.db)
        self.container.register("resource_manager", resource_mgr)

        personality = PersonalitySystem()
        self.container.register("personality", personality)

        maps = MapSystem(self.db)
        self.container.register("map_system", maps)

        llm = LLMEngine(self.flags)
        self.container.register("llm", llm)

        experience = ExperienceEngine(self.db, llm=llm)
        self.container.register("experience", experience)

    def _init_resources(self):
        resource_mgr = self.container.require("resource_manager")
        resource_mgr.init_defaults()

        survival = SurvivalAssessmentEngine(self.db, resource_mgr)
        self.container.register("survival_engine", survival)

        planner = MissionPlanner(self.db, resource_mgr)
        self.container.register("mission_planner", planner)

    def _load_knowledge(self):
        registry = self.registry
        if not registry.should_load("knowledge_fts"):
            return

        knowledge = KnowledgeEngine(self.db)
        self.container.register("knowledge", knowledge)
        registry.register("knowledge_fts", knowledge)

        from allspark.knowledge_data import get_tier0_knowledge
        from allspark.knowledge_data_en import get_tier0_knowledge_en
        from allspark.knowledge_data_tier12 import get_tier1_knowledge, get_tier2_knowledge

        for entry in get_tier0_knowledge():
            if self.db.get_knowledge(entry.id) is None:
                self.db.save_knowledge(entry)
        for entry in get_tier0_knowledge_en():
            if self.db.get_knowledge(entry.id) is None:
                self.db.save_knowledge(entry)
        for entry in get_tier1_knowledge():
            if self.db.get_knowledge(entry.id) is None:
                self.db.save_knowledge(entry)
        for entry in get_tier2_knowledge():
            if self.db.get_knowledge(entry.id) is None:
                self.db.save_knowledge(entry)

    def _register_conditional_services(self):
        registry = self.registry
        container = self.container
        llm = container.get("llm")

        if self.flags.llm:
            loaded = llm.load()
            if loaded:
                registry.register("llm", llm)

        if self.flags.multilingual_knowledge:
            registry.register("multilingual", True)
        if self.flags.self_learning:
            registry.register("self_learning", True)
        if self.flags.offline_map:
            registry.register("offline_map", container.get("map_system"))
        if self.flags.self_learning:
            registry.register("self_learning", container.get("experience"))

        if registry.should_load("governance"):
            from allspark.governance import GovernanceEngine
            gov = GovernanceEngine(db=self.db, llm_engine=llm)
            container.register("governance", gov)
            registry.register("governance", gov)

        if registry.should_load("trade_engine"):
            from allspark.trade_engine import TradeEngine
            network = registry.get("spark_network")
            verifier = registry.get("knowledge_verifier")
            trade = TradeEngine(db=self.db, network=network, verifier=verifier)
            container.register("trade_engine", trade)
            registry.register("trade_engine", trade)

        if registry.should_load("power_monitor"):
            from allspark.power_monitor import PowerMonitor
            pm = PowerMonitor(db=self.db)
            container.register("power_monitor", pm)
            registry.register("power_monitor", pm)

        if registry.should_load("sensor_hub"):
            from allspark.sensor_hub import SensorHub
            hub = SensorHub(db=self.db)
            container.register("sensor_hub", hub)
            registry.register("sensor_hub", hub)

        data_preservation = None
        if registry.should_load("data_preservation"):
            from allspark.data_preservation import DataPreservation
            data_preservation = DataPreservation(db=self.db)
            container.register("data_preservation", data_preservation)
            registry.register("data_preservation", data_preservation)
            integrity = data_preservation.startup_integrity_check()
            if integrity.get("warnings"):
                logger.warning(f"Startup integrity check: {integrity['warnings']}")

        if registry.should_load("boot_manager"):
            from allspark.boot_manager import BootManager
            bm = BootManager(db=self.db)
            container.register("boot_manager", bm)
            registry.register("boot_manager", bm)

        resource_mgr = container.require("resource_manager")
        survival = container.require("survival_engine")
        personality = container.get("personality")

        if registry.should_load("goal_engine"):
            from allspark.goal_engine import GoalEngine
            ge = GoalEngine(db=self.db, resource_mgr=resource_mgr, survival=survival)
            container.register("goal_engine", ge)
            registry.register("goal_engine", ge)

        if registry.should_load("reset_manager"):
            from allspark.reset_manager import ResetManager
            rm = ResetManager(
                db=self.db,
                data_preservation=data_preservation,
                resource_mgr=resource_mgr,
                docker_manager=container.get("docker_manager"),
            )
            container.register("reset_manager", rm)
            registry.register("reset_manager", rm)

        goal_engine = container.get("goal_engine")

        if registry.should_load("daily_briefing"):
            from allspark.daily_briefing import DailyBriefing
            db_svc = DailyBriefing(
                db=self.db, resource_mgr=resource_mgr,
                survival=survival,
                goal_engine=goal_engine,
                personality=personality,
            )
            container.register("daily_briefing", db_svc)
            registry.register("daily_briefing", db_svc)

        if registry.should_load("timeline"):
            from allspark.timeline import TimelineManager
            tl = TimelineManager(
                db=self.db,
                experience_engine=container.get("experience"),
            )
            container.register("timeline", tl)
            registry.register("timeline", tl)

        if registry.should_load("diary"):
            from allspark.diary import DiaryManager
            diary = DiaryManager(
                db=self.db,
                timeline=container.get("timeline"),
            )
            container.register("diary", diary)
            registry.register("diary", diary)

        sensor_hub = container.get("sensor_hub")

        if registry.should_load("weather"):
            from allspark.weather import WeatherPredictor
            weather = WeatherPredictor(
                db=self.db,
                sensor_hub=sensor_hub,
            )
            container.register("weather", weather)
            registry.register("weather", weather)

        if registry.should_load("psychology"):
            from allspark.psychology import PsychologyTracker
            psych = PsychologyTracker(
                db=self.db,
                personality=personality,
            )
            container.register("psychology", psych)
            registry.register("psychology", psych)

        if registry.should_load("gps_manager"):
            from allspark.gps_manager import GPSManager
            gps = GPSManager(
                db=self.db,
                sensor_hub=sensor_hub,
            )
            container.register("gps_manager", gps)
            registry.register("gps_manager", gps)

        weather = container.get("weather")

        if registry.should_load("environment"):
            from allspark.environment import EnvironmentAssessor
            env = EnvironmentAssessor(
                db=self.db,
                weather=weather,
                resource_mgr=resource_mgr,
                survival=survival,
            )
            container.register("environment", env)
            registry.register("environment", env)

        diary = container.get("diary")

        if registry.should_load("voice"):
            from allspark.voice import VoiceManager
            voice = VoiceManager(
                db=self.db,
                diary=diary,
                llm_engine=llm,
            )
            container.register("voice", voice)
            registry.register("voice", voice)

    def _init_docker(self):
        if not self.flags.docker_enabled:
            return

        from allspark.docker_manager import DockerManager

        deploy_mode = DeployMode(self.flags.deploy_mode)
        docker_mgr = DockerManager(
            db=self.db,
            flags=self.flags,
            deploy_mode=deploy_mode,
        )

        if not docker_mgr.is_docker_available():
            logger.warning(t("docker_fallback_to_process"))
            self.flags.deploy_mode = "process"
            self.flags.docker_enabled = False
            self.flags.docker_services = []
            return

        container = self.container
        container.register("docker_manager", docker_mgr)
        self.registry.register("docker_manager", docker_mgr)

        try:
            docker_mgr.start_all()
            logger.info(t("docker_started"))
        except Exception as e:
            logger.warning(f"Docker start failed, falling back to process mode: {e}")
            self.flags.deploy_mode = "process"
            self.flags.docker_enabled = False
            self.flags.docker_services = []
