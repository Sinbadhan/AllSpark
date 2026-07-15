from datetime import datetime, timedelta, timezone
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from rich.console import Console

from allspark.adapters.cli import SparkCLI
from allspark.adapters.routes.core import _resource_payload
from allspark.adapters.web_ui import create_app
from allspark.bootstrap import ApplicationBootstrap
from allspark.commands.ai import LLMCommand
from allspark.commands.basic import StatusCommand
from allspark.core.database import Database
from allspark.core.i18n import t
from allspark.core.models import Goal, OperatingMode, Resource, ResourceType
from allspark.infrastructure.hardware import FeatureFlags
from allspark.infrastructure.module_loader import ModuleRegistry
from allspark.services.daily_briefing import DailyBriefing
from allspark.services.environment import EnvironmentAssessor
from allspark.services.goal_engine import GoalEngine
from allspark.services.knowledge_engine import KnowledgeEngine
from allspark.services.llm_engine import LLMEngine
from allspark.services.mission_planner import MissionPlanner
from allspark.services.personality import PersonalitySystem
from allspark.services.power_monitor import PowerMonitor
from allspark.services.priority_calculator import PriorityCalculator
from allspark.services.psychology import PsychologyTracker
from allspark.services.resource_manager import ResourceManager
from allspark.services.rule_engine import RuleEngine
from allspark.services.survival_engine import SurvivalAssessmentEngine


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "sha248.db"))
    yield database
    database.close()


@pytest.fixture
def resource_manager(db):
    manager = ResourceManager(db)
    manager.init_defaults()
    return manager


def _resource(
    resource_type: ResourceType,
    days: float,
    *,
    as_of: str | None = None,
) -> Resource:
    consumption = 1.0
    amount = days * consumption
    return Resource(
        type=resource_type,
        current_amount=amount,
        unit={ResourceType.WATER: "L", ResourceType.FOOD: "kcal"}[resource_type],
        daily_consumption=consumption,
        daily_intake=0.0,
        rate_basis="group_total",
        estimated_remaining_hours=days * 24.0,
        amount_known=True,
        consumption_known=True,
        intake_known=True,
        source="user_input",
        people_count=1,
        people_count_known=True,
        as_of=as_of or datetime.now(timezone.utc).isoformat(),
    )


def _save_fresh_pair(db, *, water_days: float, food_days: float) -> None:
    db.upsert_resource(_resource(ResourceType.WATER, water_days))
    db.upsert_resource(_resource(ResourceType.FOOD, food_days))


@pytest.mark.parametrize(
    ("resource_type", "attribute", "expected"),
    [
        (ResourceType.WATER, "amount_known", "water.amount"),
        (ResourceType.WATER, "consumption_known", "water.consumption"),
        (ResourceType.WATER, "intake_known", "water.intake"),
        (ResourceType.WATER, "rate_basis", "water.rate_basis"),
        (ResourceType.FOOD, "amount_known", "food.amount"),
        (ResourceType.FOOD, "consumption_known", "food.consumption"),
        (ResourceType.FOOD, "intake_known", "food.intake"),
        (ResourceType.FOOD, "rate_basis", "food.rate_basis"),
    ],
)
def test_phase_is_unknown_for_each_missing_critical_field(
    db, resource_manager, resource_type, attribute, expected
):
    _save_fresh_pair(db, water_days=30, food_days=30)
    resource = db.get_resource(resource_type)
    assert resource is not None
    setattr(resource, attribute, False if attribute.endswith("_known") else "unknown")
    db.upsert_resource(resource)

    result = SurvivalAssessmentEngine(db, resource_manager).assess()

    assert result["phase"] is None
    assert result["phase_status"] == "unknown"
    assert result["missing_fields"] == [expected]
    assert result["stale_fields"] == []
    assert "None" not in result["phase_description"]


@pytest.mark.parametrize(
    "as_of",
    ["", "not-a-timestamp", (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()],
)
def test_phase_is_unknown_when_snapshot_is_missing_invalid_or_stale(
    db, resource_manager, as_of
):
    _save_fresh_pair(db, water_days=30, food_days=30)
    water = db.get_resource(ResourceType.WATER)
    assert water is not None
    water.as_of = as_of
    db.upsert_resource(water)

    result = SurvivalAssessmentEngine(db, resource_manager).assess()

    assert result["phase"] is None
    assert result["phase_status"] == "unknown"
    assert result["missing_fields"] == []
    assert result["stale_fields"] == ["water.as_of"]
    assert result["bottleneck"] is None


def test_all_unknown_fields_have_stable_water_then_food_order(db, resource_manager):
    result = SurvivalAssessmentEngine(db, resource_manager).assess()

    assert result["missing_fields"] == [
        "water.amount",
        "water.consumption",
        "water.intake",
        "water.rate_basis",
        "food.amount",
        "food.consumption",
        "food.intake",
        "food.rate_basis",
    ]
    assert result["stale_fields"] == ["water.as_of", "food.as_of"]


def test_missing_resource_maps_all_fields_in_same_stable_order(db):
    result = SurvivalAssessmentEngine(db, ResourceManager(db)).assess()

    assert result["missing_fields"] == [
        "water.amount",
        "water.consumption",
        "water.intake",
        "water.rate_basis",
        "food.amount",
        "food.consumption",
        "food.intake",
        "food.rate_basis",
    ]
    assert result["stale_fields"] == ["water.as_of", "food.as_of"]


def test_exactly_24_hours_is_current_but_older_is_stale(
    db, resource_manager, monkeypatch
):
    fixed_now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    clock_calls: list[datetime] = []

    def fixed_clock() -> datetime:
        clock_calls.append(fixed_now)
        return fixed_now

    monkeypatch.setattr(
        SurvivalAssessmentEngine,
        "_now_utc",
        staticmethod(fixed_clock),
    )
    _save_fresh_pair(db, water_days=30, food_days=30)
    water = db.get_resource(ResourceType.WATER)
    food = db.get_resource(ResourceType.FOOD)
    assert water is not None and food is not None
    water.as_of = (fixed_now - timedelta(hours=24)).isoformat()
    food.as_of = fixed_now.replace(tzinfo=None).isoformat()
    db.upsert_resource(water)
    db.upsert_resource(food)

    exact_boundary = SurvivalAssessmentEngine(db, resource_manager).assess()
    assert exact_boundary["phase_status"] == "known"
    assert exact_boundary["phase"] is not None
    assert exact_boundary["stale_fields"] == []
    assert len(clock_calls) == 1

    water.as_of = (fixed_now - timedelta(hours=24, microseconds=1)).isoformat()
    db.upsert_resource(water)
    result = SurvivalAssessmentEngine(db, resource_manager).assess()
    assert result["phase"] is None
    assert result["stale_fields"] == ["water.as_of"]
    assert len(clock_calls) == 2


@pytest.mark.parametrize(
    ("water_days", "food_days", "expected_phase"),
    [
        (2.99, 20, 0),
        (10, 6.99, 1),
        (179.99, 100, 2),
        (1799.99, 1000, 3),
        (1800, 900, 4),
    ],
)
def test_fresh_complete_resources_cover_phase_boundaries(
    db, resource_manager, water_days, food_days, expected_phase
):
    _save_fresh_pair(db, water_days=water_days, food_days=food_days)

    result = SurvivalAssessmentEngine(db, resource_manager).assess()

    assert result["phase"] == expected_phase
    assert result["phase_status"] == "known"
    assert result["missing_fields"] == []
    assert result["stale_fields"] == []


def test_unknown_phase_does_not_generate_phase_goals_or_missions(
    db, resource_manager
):
    survival = SurvivalAssessmentEngine(db, resource_manager)
    goals = GoalEngine(db, resource_manager, survival)
    planner = MissionPlanner(db, resource_manager)

    generated = goals.auto_generate_goals()
    suggested = planner.suggest_tasks(resource_manager.get_all_resources(), phase=None)

    assert generated == []
    assert suggested == []
    assert db.get_active_tasks() == []


def test_stale_resource_does_not_generate_urgent_task_or_goal(db, resource_manager):
    stale = datetime.now(timezone.utc) - timedelta(hours=25)
    water = _resource(ResourceType.WATER, 1, as_of=stale.isoformat())
    food = _resource(ResourceType.FOOD, 30)
    db.upsert_resource(water)
    db.upsert_resource(food)
    survival = SurvivalAssessmentEngine(db, resource_manager)
    assessment = survival.assess()
    planner = MissionPlanner(db, resource_manager)
    goals = GoalEngine(db, resource_manager, survival)

    tasks = planner.suggest_tasks(
        assessment["resources"],
        phase=assessment["phase"],
        stale_fields=assessment["stale_fields"],
    )

    assert tasks == []
    assert goals.auto_generate_goals() == []
    assert db.get_active_tasks() == []


def test_stale_fire_does_not_lower_phase(db, resource_manager):
    _save_fresh_pair(db, water_days=100, food_days=100)
    fire = Resource(
        type=ResourceType.FIRE,
        current_amount=0,
        unit="uses",
        amount_known=True,
        as_of=(datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
    )
    db.upsert_resource(fire)

    assert SurvivalAssessmentEngine(db, resource_manager).assess()["phase"] == 2


def test_stale_noncritical_resource_is_not_precise_bottleneck(db, resource_manager):
    _save_fresh_pair(db, water_days=100, food_days=100)
    power = Resource(
        type=ResourceType.POWER,
        current_amount=1,
        unit="Wh",
        daily_consumption=24,
        daily_intake=0,
        rate_basis="group_total",
        estimated_remaining_hours=1,
        amount_known=True,
        consumption_known=True,
        intake_known=True,
        as_of=(datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
    )
    db.upsert_resource(power)

    assert SurvivalAssessmentEngine(db, resource_manager).assess()["bottleneck"] is None


@pytest.mark.parametrize("resource_type", list(ResourceType))
def test_stale_resources_do_not_emit_precise_warnings(
    db, resource_manager, resource_type
):
    unit = {
        ResourceType.POWER: "Wh",
        ResourceType.WATER: "L",
        ResourceType.FOOD: "kcal",
        ResourceType.FIRE: "uses",
        ResourceType.STORAGE: "GB",
    }[resource_type]
    resource = Resource(
        type=resource_type,
        current_amount=1,
        unit=unit,
        daily_consumption=24,
        daily_intake=0,
        rate_basis="group_total",
        estimated_remaining_hours=1,
        amount_known=True,
        consumption_known=True,
        intake_known=True,
        capacity=100,
        capacity_known=True,
        as_of=(datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
    )
    db.upsert_resource(resource)

    assert resource_manager.check_warnings() == []


def test_stale_power_does_not_change_mode_or_remaining_state(db, resource_manager):
    state = db.get_operating_state()
    state.mode = OperatingMode.ECONOMY.value
    state.power_remaining_hours = 77
    db.save_operating_state(state)
    power = Resource(
        type=ResourceType.POWER,
        current_amount=1,
        unit="Wh",
        daily_consumption=24,
        daily_intake=0,
        rate_basis="group_total",
        estimated_remaining_hours=1,
        amount_known=True,
        consumption_known=True,
        intake_known=True,
        as_of=(datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
    )
    db.upsert_resource(power)

    mode, changed = resource_manager.update_operating_mode()
    persisted = db.get_operating_state()

    assert (mode, changed) == (OperatingMode.ECONOMY, False)
    assert persisted.mode == OperatingMode.ECONOMY.value
    assert persisted.power_remaining_hours == 77


def test_manual_mode_override_still_wins_with_stale_power(db, resource_manager):
    state = db.get_operating_state()
    state.mode = OperatingMode.HIBERNATION.value
    state.mode_manual_override = True
    db.save_operating_state(state)

    assert resource_manager.update_operating_mode() == (
        OperatingMode.HIBERNATION,
        False,
    )


def test_fresh_power_keeps_existing_mode_behavior(db, resource_manager):
    power = Resource(
        type=ResourceType.POWER,
        current_amount=1,
        unit="Wh",
        daily_consumption=24,
        daily_intake=0,
        rate_basis="group_total",
        estimated_remaining_hours=1,
        amount_known=True,
        consumption_known=True,
        intake_known=True,
        as_of=datetime.now(timezone.utc).isoformat(),
    )
    db.upsert_resource(power)

    mode, changed = resource_manager.update_operating_mode()

    assert mode == OperatingMode.HIBERNATION
    assert changed is True


def test_stale_remaining_is_unknown_across_api_cli_and_briefing(
    db, resource_manager
):
    stale_power = Resource(
        type=ResourceType.POWER,
        current_amount=1,
        unit="Wh",
        daily_consumption=24,
        daily_intake=0,
        rate_basis="group_total",
        estimated_remaining_hours=1,
        amount_known=True,
        consumption_known=True,
        intake_known=True,
        as_of=(datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
    )
    db.upsert_resource(stale_power)
    payload = _resource_payload(resource_manager, stale_power)
    briefing = DailyBriefing(db, resource_mgr=resource_manager).generate_short()
    summary = resource_manager.get_resource_summary()

    container = ApplicationBootstrap(db, flags=FeatureFlags()).bootstrap()
    command = StatusCommand(container)
    output = StringIO()
    command.console = Console(file=output, force_terminal=False)
    command.execute([])

    assert payload["remaining_status"] == "unknown"
    assert payload["remaining_hours"] is None
    assert t(
        "resource_snapshot_stale",
        label=t("resource_power"),
        amount=1.0,
        unit="Wh",
    ) in summary
    assert "1.0h" not in summary
    assert "(1h)" not in briefing
    assert "1.0h" not in output.getvalue()


def test_stale_remaining_does_not_drive_psychology_priority_or_power_runtime(
    db, resource_manager
):
    stale_power = Resource(
        type=ResourceType.POWER,
        current_amount=1,
        unit="Wh",
        daily_consumption=24,
        daily_intake=0,
        rate_basis="group_total",
        estimated_remaining_hours=1,
        amount_known=True,
        consumption_known=True,
        intake_known=True,
        as_of=(datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
    )
    db.upsert_resource(stale_power)
    psychology = PsychologyTracker(db, resource_mgr=resource_manager)
    priority = PriorityCalculator(db, resource_mgr=resource_manager)
    goal = Goal(id="stale-power", title="Power", category="survival")
    monitor = PowerMonitor(db, resource_manager=resource_manager)

    assert psychology._calculate_stress() == 0
    assert priority._calc_urgency(goal, {}) == 0.5
    assert monitor.estimate_runtime() == {
        "estimated_hours": None,
        "mode_recommendation": "unknown",
    }


def test_stale_resources_do_not_enter_knowledge_or_llm_context(
    db, resource_manager
):
    stale_water = _resource(
        ResourceType.WATER,
        1,
        as_of=(datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
    )
    db.upsert_resource(stale_water)
    knowledge = KnowledgeEngine(db)
    searches: list[str] = []
    knowledge.search_by_language = (
        lambda query, limit=5: searches.append(query) or []
    )
    assert knowledge.get_relevant_knowledge("nothing", [stale_water]) == []
    assert searches == ["nothing"]

    container = ApplicationBootstrap(db, flags=FeatureFlags()).bootstrap()
    engine = RuleEngine(container)
    captured: dict[str, object] = {}

    class LLM:
        available = True

        def survival_chat(self, message, *, context="", phase=None):
            captured.update(context=context, phase=phase)
            return "answer"

    engine.llm = LLM()
    engine._handle_general("question", [stale_water], [], None)
    assert captured == {"context": "", "phase": None}


def test_unknown_phase_is_not_used_as_briefing_category(db, resource_manager):
    survival = SurvivalAssessmentEngine(db, resource_manager)
    briefing = DailyBriefing(db, resource_mgr=resource_manager, survival=survival)

    assert briefing._get_relevant_categories() == [
        "power",
        "energy",
        "electricity",
        "solar",
        "battery",
        "water",
        "purification",
        "hydration",
        "rain",
        "food",
        "foraging",
        "hunting",
        "agriculture",
        "edible",
        "fire",
        "warmth",
        "cooking",
        "shelter",
        "storage",
        "preservation",
    ]


def test_unknown_phase_does_not_promote_personality_mode():
    personality = PersonalitySystem()

    mode = personality.determine_mode(OperatingMode.STANDARD, [], None)

    assert mode.value == "stable"


def test_llm_prompt_uses_unknown_truth_instead_of_phase_zero():
    llm = LLMEngine.__new__(LLMEngine)

    prompt = llm._build_system_prompt(None)

    assert "Current survival phase: unknown" in prompt
    assert "immediate survival" not in prompt


def test_unknown_assessment_summary_uses_dedicated_i18n(db, resource_manager):
    summary = SurvivalAssessmentEngine(db, resource_manager).get_assessment_summary()

    assert "phase_desc_None" not in summary
    assert "phase_fallback_None" not in summary


def test_environment_does_not_treat_unknown_phase_as_stable(db):
    survival = SimpleNamespace(assess=lambda: {"phase": None, "phase_status": "unknown"})
    assessor = EnvironmentAssessor(db=db, survival=survival)
    evidence = {
        ResourceType.POWER.value: {"status": "healthy"},
    }

    result = assessor._assess_opportunities(True, evidence)

    assert all("stable" not in item.lower() for item in result["items"])


def test_rule_engine_unknown_status_and_fallback_do_not_create_phase_zero_tasks(
    db, resource_manager
):
    container = ApplicationBootstrap(db, flags=FeatureFlags()).bootstrap()
    engine = RuleEngine(container)

    status = engine.process_input("status")
    fallback = engine.process_input("zzzz-no-matching-knowledge")

    assert "phase_desc_None" not in status
    assert "phase_fallback_None" not in fallback
    assert db.get_active_tasks() == []


def _initialized_client(path) -> TestClient:
    db = Database(str(path))
    try:
        db.mark_initialized()
        ModuleRegistry(FeatureFlags()).save_to_db(db)
    finally:
        db.close()
    return TestClient(create_app(str(path)))


def test_core_routes_transmit_unknown_phase_contract(tmp_path):
    client = _initialized_client(tmp_path / "routes.db")

    status = client.get("/api/status")
    chat = client.post("/api/chat", json={"message": "status"})
    stream = client.post("/api/chat/stream", json={"message": "status"})

    assert status.status_code == 200
    payload = status.json()
    assert payload["phase"] is None
    assert payload["phase_status"] == "unknown"
    assert payload["missing_fields"][:4] == [
        "water.amount",
        "water.consumption",
        "water.intake",
        "water.rate_basis",
    ]
    assert payload["stale_fields"] == ["water.as_of", "food.as_of"]
    assert chat.status_code == 200
    assert "phase_desc_None" not in chat.json()["response"]
    assert stream.status_code == 200
    assert "immediate survival" not in stream.text


def test_cli_initial_status_accepts_unknown_phase(db, monkeypatch):
    container = ApplicationBootstrap(db, flags=FeatureFlags()).bootstrap()
    cli = SparkCLI.__new__(SparkCLI)
    cli.db = db
    cli.container = container
    output = StringIO()
    monkeypatch.setattr(
        "allspark.adapters.cli.console",
        Console(file=output, force_terminal=False),
    )

    cli._print_initial_status()

    assert "phase_desc_None" not in output.getvalue()


def test_llm_command_reads_phase_from_assessment_dict(db):
    observed: list[int | None] = []
    llm = SimpleNamespace(
        available=True,
        survival_chat=lambda message, *, phase: observed.append(phase) or "ok",
    )
    survival = SimpleNamespace(assess=lambda: {"phase": None})
    registry = MagicMock()

    class Container:
        def __init__(self):
            self.db = db

        def get(self, name):
            return llm if name == "llm" else None

        def require(self, name):
            return {"registry": registry, "survival_engine": survival}[name]

    command = LLMCommand(Container())
    command.console = Console(file=StringIO(), force_terminal=False)

    command.execute(["chat", "hello"])

    assert observed == [None]
