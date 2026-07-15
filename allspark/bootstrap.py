import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from allspark.container import ServiceContainer
from allspark.core.database import Database
from allspark.core.i18n import t
from allspark.core.models import OperatingMode
from allspark.infrastructure.hardware import (
    DeployMode,
    FeatureFlags,
    compute_feature_flags,
    detect_hardware,
    resolve_runtime_deploy_mode,
)
from allspark.infrastructure.module_loader import ModuleRegistry
from allspark.services.experience_engine import ExperienceEngine
from allspark.services.initial_assessment import InitialAssessmentService
from allspark.services.knowledge_engine import KnowledgeEngine
from allspark.services.knowledge_verifier import KnowledgeVerifier
from allspark.services.llm_engine import LLMEngine
from allspark.services.map_system import MapSystem
from allspark.services.mission_planner import MissionPlanner
from allspark.services.personality import PersonalitySystem
from allspark.services.resource_manager import ResourceManager
from allspark.services.rule_engine import RuleEngine
from allspark.services.scheduler import create_default_scheduler
from allspark.services.survival_engine import SurvivalAssessmentEngine
from allspark.services.vision_engine import VisionEngine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedApplication:
    """A fully prepared runtime that has not yet been published by an adapter."""

    bootstrap: "ApplicationBootstrap"
    container: ServiceContainer
    engine: RuleEngine


def rollback_initialization_draft(db: Database) -> None:
    """Best-effort cleanup for a failed self-committing draft write."""
    try:
        db.conn.rollback()
    except Exception:
        logger.exception("Failed to roll back initialization draft transaction")


def cleanup_application_candidate(bootstrap: Any) -> None:
    """Best-effort runtime cleanup that never hides the initiating failure."""
    try:
        bootstrap.shutdown()
    except Exception:
        logger.exception("Failed to clean up initialization candidate")


def prepare_application(
    db: Database, flags: FeatureFlags | None = None
) -> PreparedApplication:
    """Build and validate a candidate runtime without publishing adapter state."""
    bootstrap = ApplicationBootstrap(db, flags=flags)
    try:
        container = bootstrap.bootstrap()
        engine = container.require("rule_engine")
        return PreparedApplication(bootstrap, container, engine)
    except Exception:
        rollback_initialization_draft(db)
        cleanup_application_candidate(bootstrap)
        raise


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
        self.registry.register(
            "rule_engine", self.container.get("rule_engine")
        )
        self._register_scheduler()
        self._init_docker()
        self.registry.save_to_db(self.db)
        return self.container

    def shutdown(self):
        """Clean up services already instantiated by this candidate runtime."""
        try:
            services = self.container.all_services()
        except Exception:
            logger.exception("Failed to enumerate candidate runtime services")
            return
        scheduler = services.get("scheduler")
        if scheduler:
            try:
                scheduler.stop()
                logger.info("Scheduler stopped")
            except Exception:
                logger.exception("Failed to stop candidate scheduler")

        docker_manager = services.get("docker_manager")
        if docker_manager:
            try:
                docker_manager.stop_all()
                logger.info("Docker services stopped")
            except Exception:
                logger.exception("Failed to stop candidate Docker services")

    def recover(self) -> ServiceContainer:
        """Recovery mode: data integrity check → sync data → re-evaluate.

        Called when resuming from hibernation or after unexpected shutdown.
        """
        logger.info(t("recovery_start") if hasattr(t, '__call__') else "Recovery: starting recovery sequence")

        container = self.bootstrap()

        # Step 1: Data integrity check
        self._check_data_integrity()

        # Step 2: Sync hibernation-period data
        self._sync_hibernation_data()

        # Step 3: Re-evaluate survival state
        self._re_evaluate_state(container)

        # Set operating mode to recovery
        current_state = self.db.get_operating_state()
        current_state.mode = OperatingMode.RECOVERY.value
        self.db.save_operating_state(current_state)

        logger.info("Recovery: sequence complete")
        return container

    def _check_data_integrity(self) -> dict:
        """Verify database integrity after unexpected shutdown."""
        result: dict[str, Any] = {"ok": True, "issues": []}

        try:
            check = self.db.conn.execute("PRAGMA integrity_check").fetchone()
            if check[0] != "ok":
                result["ok"] = False
                result["issues"].append(f"Database integrity: {check[0]}")
                logger.warning(f"Database integrity check failed: {check[0]}")
        except Exception as e:
            result["ok"] = False
            result["issues"].append(f"Integrity check error: {e}")

        # Verify critical tables exist
        critical_tables = ["operating_state", "resources", "knowledge", "survivor_state"]
        for table in critical_tables:
            try:
                self.db.conn.execute(f"SELECT COUNT(*) FROM {table} LIMIT 1")
            except Exception:
                result["issues"].append(f"Missing or corrupt table: {table}")

        if result["issues"]:
            result["ok"] = False

        return result

    def _sync_hibernation_data(self):
        """Synchronize data that may have changed during hibernation."""
        # Update heartbeat
        try:
            self.db.conn.execute(
                "INSERT OR REPLACE INTO operating_state VALUES (?, ?)",
                ("last_heartbeat", datetime.now().isoformat())
            )
            self.db.conn.execute(
                "INSERT OR REPLACE INTO operating_state VALUES (?, ?)",
                ("last_recovery", datetime.now().isoformat())
            )
            self.db.conn.commit()
        except Exception as e:
            logger.warning(f"Failed to sync hibernation data: {e}")

    def _re_evaluate_state(self, container: ServiceContainer):
        """Re-evaluate survival state after recovery."""
        try:
            survival = container.get("survival_engine")
            if survival:
                survival.assess()

            resource_mgr = container.get("resource_manager")
            if resource_mgr:
                resource_mgr.check_warnings()
        except Exception as e:
            logger.warning(f"Re-evaluation failed: {e}")

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

        # LocalVisionEngine is optional; startup degrades if ONNX/model missing.
        from allspark.services.local_vision import LocalVisionEngine
        local_vision = LocalVisionEngine(self.db)
        local_vision.startup()
        self.container.register("local_vision", local_vision)

        # VisionEngine — facade over LLM multimodal + local ONNX vision; built
        # lazily via factory so routes/commands don't construct it manually
        # (audit L2). Construction is cheap; multimodal detection defers to llm.
        self.container.register_factory(
            "vision",
            lambda: VisionEngine(
                llm_engine=self.container.get("llm"),
                db=self.db,
                local_vision=self.container.get("local_vision"),
            ),
        )

        experience = ExperienceEngine(self.db, llm=llm)
        self.container.register("experience", experience)

        # RuleEngine — core decision engine, registered via factory to keep
        # _register_core_services free of cross-service wiring.
        self.container.register_factory(
            "rule_engine",
            lambda: RuleEngine(self.container),
        )

        # KnowledgeVerifier — used by CLI/Web verification flows; keep construction
        # centralized so routes don't manually instantiate services.
        self.container.register_factory(
            "knowledge_verifier",
            lambda: KnowledgeVerifier(self.db, self.container.get("llm")),
        )

    def _init_resources(self):
        resource_mgr = self.container.require("resource_manager")
        resource_mgr.init_defaults()

        survival = SurvivalAssessmentEngine(self.db, resource_mgr)
        self.container.register("survival_engine", survival)

        planner = MissionPlanner(self.db, resource_mgr)
        self.container.register("mission_planner", planner)

        initial_assessment = InitialAssessmentService(self.db, resource_mgr)
        self.container.register("initial_assessment", initial_assessment)

    def _load_knowledge(self):
        registry = self.registry
        if not registry.should_load("knowledge_fts"):
            return

        vector_engine = None
        if getattr(self.flags, "vector_rag", False):
            from allspark.services.vector_engine import VectorEngine
            vector_engine = VectorEngine(self.db, flags=self.flags)
            vector_engine.startup()
            self.container.register("vector_engine", vector_engine)

        external_kb = None
        if getattr(self.flags, "kiwix", False):
            from allspark.services.external_kb import ExternalKBService
            external_kb = ExternalKBService(self.db)
            self.container.register("external_kb", external_kb)

        knowledge = KnowledgeEngine(self.db, vector_engine=vector_engine, external_kb=external_kb)
        self.container.register("knowledge", knowledge)
        registry.register("knowledge_fts", knowledge)

        from allspark.services.knowledge_loader import load_knowledge

        for entry in load_knowledge(tier=-1):
            self.db.save_bundled_knowledge(entry)

        if vector_engine and vector_engine.is_available():
            vector_engine.reindex_all()

    def _register_conditional_services(self):
        registry = self.registry
        container = self.container
        llm = container.require("llm")

        if self.flags.llm:
            loaded = llm.load()
            if loaded:
                registry.register("llm", llm)

        if self.flags.multilingual_knowledge:
            registry.register("multilingual", True)
        if self.flags.offline_map:
            registry.register("offline_map", container.get("map_system"))
        if self.flags.self_learning:
            registry.register("self_learning", container.get("experience"))

        if registry.should_load("governance"):
            from allspark.services.governance import GovernanceEngine
            gov = GovernanceEngine(db=self.db, llm_engine=llm)
            container.register("governance", gov)
            registry.register("governance", gov)

        if registry.should_load("trade_engine"):
            from allspark.services.trade_engine import TradeEngine
            network = registry.get("spark_network")
            verifier = registry.get("knowledge_verifier")
            trade = TradeEngine(db=self.db, network=network, verifier=verifier)
            container.register("trade_engine", trade)
            registry.register("trade_engine", trade)

        if registry.should_load("power_monitor"):
            from allspark.services.power_monitor import PowerMonitor
            pm = PowerMonitor(
                db=self.db,
                resource_manager=container.get("resource_manager"),
            )
            container.register("power_monitor", pm)
            registry.register("power_monitor", pm)

        if registry.should_load("sensor_hub"):
            from allspark.services.sensor_hub import SensorHub
            hub = SensorHub(db=self.db)
            container.register("sensor_hub", hub)
            registry.register("sensor_hub", hub)

        data_preservation = None
        if registry.should_load("data_preservation"):
            from allspark.infrastructure.data_preservation import DataPreservation
            data_preservation = DataPreservation(db=self.db)
            container.register("data_preservation", data_preservation)
            registry.register("data_preservation", data_preservation)
            integrity = data_preservation.startup_integrity_check()
            if integrity.get("warnings"):
                logger.warning(f"Startup integrity check: {integrity['warnings']}")

        if registry.should_load("boot_manager"):
            from allspark.infrastructure.boot_manager import BootManager
            bm = BootManager(db=self.db)
            container.register("boot_manager", bm)
            registry.register("boot_manager", bm)

        resource_mgr = container.require("resource_manager")
        survival = container.require("survival_engine")
        personality = container.get("personality")

        if registry.should_load("goal_engine"):
            from allspark.services.goal_engine import GoalEngine
            ge = GoalEngine(db=self.db, resource_mgr=resource_mgr, survival=survival)
            container.register("goal_engine", ge)
            registry.register("goal_engine", ge)

        # PriorityCalculator (PRD §10.4) — used by GoalEngine and WarningProtocol
        from allspark.services.priority_calculator import PriorityCalculator
        pc = PriorityCalculator(self.db, resource_mgr=resource_mgr)
        container.register("priority_calculator", pc)

        # WarningProtocol (PRD §3.1.3) — resource warning closed-loop
        from allspark.services.warning_protocol import WarningProtocol
        wp = WarningProtocol(self.db, container=container)
        container.register("warning_protocol", wp)

        if registry.should_load("reset_manager"):
            from allspark.services.reset_manager import ResetManager
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
            from allspark.services.daily_briefing import DailyBriefing
            db_svc = DailyBriefing(
                db=self.db, resource_mgr=resource_mgr,
                survival=survival,
                goal_engine=goal_engine,
                personality=personality,
            )
            container.register("daily_briefing", db_svc)
            registry.register("daily_briefing", db_svc)

        if registry.should_load("timeline"):
            from allspark.services.timeline import TimelineManager
            tl = TimelineManager(
                db=self.db,
                experience_engine=container.get("experience"),
            )
            container.register("timeline", tl)
            registry.register("timeline", tl)

        if registry.should_load("diary"):
            from allspark.services.diary import DiaryManager
            diary = DiaryManager(
                db=self.db,
                timeline=container.get("timeline"),
            )
            container.register("diary", diary)
            registry.register("diary", diary)

        sensor_hub = container.get("sensor_hub")

        if registry.should_load("weather"):
            from allspark.services.weather import WeatherPredictor
            weather = WeatherPredictor(
                db=self.db,
                sensor_hub=sensor_hub,
            )
            container.register("weather", weather)
            registry.register("weather", weather)

        if registry.should_load("psychology"):
            from allspark.services.psychology import PsychologyTracker
            psych = PsychologyTracker(
                db=self.db,
                personality=personality,
                resource_mgr=resource_mgr,
            )
            container.register("psychology", psych)
            registry.register("psychology", psych)

        if registry.should_load("gps_manager"):
            from allspark.services.gps_manager import GPSManager
            gps = GPSManager(
                db=self.db,
                sensor_hub=sensor_hub,
            )
            container.register("gps_manager", gps)
            registry.register("gps_manager", gps)

        weather_svc = container.get("weather")

        if registry.should_load("environment"):
            from allspark.services.environment import EnvironmentAssessor
            env = EnvironmentAssessor(
                db=self.db,
                weather=weather_svc,
                resource_mgr=resource_mgr,
                survival=survival,
            )
            container.register("environment", env)
            registry.register("environment", env)

        diary_svc = container.get("diary")

        if registry.should_load("voice"):
            from allspark.services.voice import VoiceManager
            voice = VoiceManager(
                db=self.db,
                diary=diary_svc,
                llm_engine=llm,
            )
            container.register("voice", voice)
            registry.register("voice", voice)

    def _register_scheduler(self):
        """Register the TaskScheduler via factory so it's lazily created."""
        self.container.register_factory(
            "scheduler",
            lambda: create_default_scheduler(self.container),
        )

    def _init_docker(self):
        if not (self.flags.docker_eligible or self.flags.docker_enabled):
            return

        from allspark.docker_manager import DockerManager

        recommended_mode = self.flags.recommended_deploy_mode
        if recommended_mode == DeployMode.PROCESS.value and self.flags.docker_enabled:
            recommended_mode = self.flags.deploy_mode
            self.flags.recommended_deploy_mode = recommended_mode
            self.flags.docker_eligible = True
            self.flags.recommended_docker_services = list(
                self.flags.docker_services
            )
        deploy_mode = DeployMode(recommended_mode)
        docker_mgr = DockerManager(
            db=self.db,
            flags=self.flags,
            deploy_mode=deploy_mode,
        )

        if not docker_mgr.is_docker_available():
            logger.warning(t("docker_fallback_to_process"))
            resolve_runtime_deploy_mode(self.flags, docker_available=False)
            return

        resolve_runtime_deploy_mode(self.flags, docker_available=True)

        try:
            docker_mgr.start_all()
            self.container.register("docker_manager", docker_mgr)
            self.registry.register("docker_manager", docker_mgr)
            logger.info(t("docker_started"))
        except Exception as e:
            logger.warning(f"Docker start failed, falling back to process mode: {e}")
            resolve_runtime_deploy_mode(self.flags, docker_available=False)
