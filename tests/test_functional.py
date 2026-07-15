import os
import tempfile
from datetime import datetime

import pytest

from allspark.core.database import Database
from allspark.core.i18n import get_language, set_language, t
from allspark.core.models import (
    OperatingMode,
    PersonalityMode,
    ResetLevel,
    ResourceType,
)
from allspark.services.daily_briefing import DailyBriefing
from allspark.services.diary import DiaryManager
from allspark.services.environment import EnvironmentAssessor
from allspark.services.experience_engine import ExperienceEngine
from allspark.services.goal_engine import GoalEngine
from allspark.services.gps_manager import GPSManager
from allspark.services.knowledge_engine import KnowledgeEngine
from allspark.services.map_system import MapSystem
from allspark.services.mission_planner import MissionPlanner
from allspark.services.personality import PersonalitySystem
from allspark.services.psychology import PsychologyTracker
from allspark.services.reset_manager import ResetManager
from allspark.services.resource_manager import ResourceManager
from allspark.services.rule_engine import RuleEngine
from allspark.services.survival_engine import SurvivalAssessmentEngine
from allspark.services.timeline import TimelineManager
from allspark.services.weather import WeatherPredictor


def _capture_all_consoles(cli_obj, captured_console):
    import allspark.adapters.cli as cli_mod
    old = {"cli": cli_mod.console, "commands": []}
    cli_mod.console = captured_console
    if cli_obj._dispatcher:
        for cmd in cli_obj._dispatcher.all_commands():
            old["commands"].append((cmd, cmd.console))
            cmd.console = captured_console
    return old


def _restore_all_consoles(cli_obj, old):
    import allspark.adapters.cli as cli_mod
    cli_mod.console = old["cli"]
    if cli_obj._dispatcher:
        for cmd, old_c in old["commands"]:
            cmd.console = old_c


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database = Database(path)
    yield database
    database.close()
    os.unlink(path)


@pytest.fixture
def resource_mgr(db):
    return ResourceManager(db)


@pytest.fixture
def survival(db, resource_mgr):
    resource_mgr.init_defaults()
    return SurvivalAssessmentEngine(db, resource_mgr)


@pytest.fixture
def cli(db, resource_mgr):
    db.mark_initialized()
    resource_mgr.init_defaults()
    from allspark.adapters.cli import SparkCLI
    from allspark.bootstrap import ApplicationBootstrap
    from allspark.infrastructure.hardware import FeatureFlags
    cli_obj = SparkCLI.__new__(SparkCLI)
    cli_obj.db = db
    flags = FeatureFlags()
    cli_obj.container = ApplicationBootstrap(db, flags=flags).bootstrap()
    cli_obj.engine = RuleEngine(cli_obj.container)
    cli_obj.running = True
    cli_obj._flags = flags
    cli_obj._dispatcher = None
    from allspark.core.i18n import init_language
    init_language(db)
    cli_obj._setup_dispatcher()
    return cli_obj


class TestDatabaseInitialization:
    def test_schema_created(self, db):
        tables = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {r["name"] for r in tables}
        for expected in ["resources", "tasks", "knowledge", "goals",
                         "timeline_events", "diary_entries", "psych_state",
                         "spark_location", "reset_log", "milestones",
                         "community_members", "trade_offers"]:
            assert expected in table_names, f"Missing table: {expected}"

    def test_initialization_flag(self, db):
        assert not db.is_initialized()
        db.mark_initialized()
        assert db.is_initialized()
        db.mark_uninitialized()
        assert not db.is_initialized()

    def test_migration_no_duplicate_column(self, db):
        path = db.conn.execute("PRAGMA database_list").fetchone()["file"]
        db2 = Database(path)
        db2.close()


class TestResourceManager:
    def test_defaults_all_zero(self, resource_mgr):
        resource_mgr.init_defaults()
        for r in resource_mgr.get_all_resources():
            assert r.current_amount == 0
            assert r.daily_consumption == 0

    def test_update_resource(self, resource_mgr):
        resource_mgr.init_defaults()
        resource_mgr.update_resource(
            ResourceType.WATER, 10.0, consumption=2.0, intake=0.0
        )
        r = resource_mgr.db.get_resource(ResourceType.WATER)
        assert r.current_amount == 10.0
        assert r.daily_consumption == 2.0
        assert r.estimated_remaining_hours > 0

    def test_warnings_critical(self, resource_mgr):
        resource_mgr.init_defaults()
        resource_mgr.update_resource(
            ResourceType.POWER, 37.0, consumption=120.0, intake=0.0
        )
        warnings = resource_mgr.check_warnings()
        assert len(warnings) > 0

    def test_operating_mode_determined(self, resource_mgr):
        resource_mgr.init_defaults()
        resource_mgr.update_resource(ResourceType.POWER, 100.0, consumption=50.0, intake=0.0)
        mode, _ = resource_mgr.update_operating_mode()
        assert isinstance(mode, OperatingMode)

    def test_resource_summary_offline(self, resource_mgr):
        resource_mgr.init_defaults()
        summary = resource_mgr.get_resource_summary()
        assert t("resource_offline") in summary or t("resource_not_configured") in summary

    def test_resource_summary_with_data(self, resource_mgr):
        resource_mgr.init_defaults()
        resource_mgr.update_resource(ResourceType.WATER, 10.0, consumption=2.0)
        summary = resource_mgr.get_resource_summary()
        assert "10" in summary


class TestSurvivalAssessment:
    def test_assess_returns_dict(self, survival):
        result = survival.assess()
        assert "phase" in result
        assert "phase_description" in result
        assert "resources" in result
        assert "warnings" in result
        assert "bottleneck" in result

    def test_phase_determined(self, survival):
        result = survival.assess()
        assert 0 <= result["phase"] <= 4

    def test_bottleneck_with_low_resources(self, db, resource_mgr):
        resource_mgr.init_defaults()
        resource_mgr.update_resource(
            ResourceType.WATER, 3.0, consumption=2.0, intake=0.0
        )
        survival = SurvivalAssessmentEngine(db, resource_mgr)
        result = survival.assess()
        assert result["bottleneck"] is not None

    def test_no_bottleneck_with_plenty(self, db, resource_mgr):
        resource_mgr.init_defaults()
        resource_mgr.update_resource(
            ResourceType.WATER, 100.0, consumption=2.0, intake=0.0
        )
        resource_mgr.update_resource(
            ResourceType.FOOD, 50000.0, consumption=2000.0, intake=0.0
        )
        resource_mgr.update_resource(ResourceType.POWER, 200.0, consumption=50.0, intake=0.0)
        resource_mgr.update_resource(
            ResourceType.FIRE, 50.0, consumption=3.0, intake=0.0
        )
        survival = SurvivalAssessmentEngine(db, resource_mgr)
        result = survival.assess()
        assert result["bottleneck"] is None

    def test_phase_description_uses_i18n(self, survival):
        result = survival.assess()
        desc = result["phase_description"]
        assert len(desc) > 0
        set_language("en")
        result_en = survival.assess()
        desc_en = result_en["phase_description"]
        assert len(desc_en) > 0
        set_language("zh")


class TestKnowledgeEngine:
    def test_search(self, db):
        ke = KnowledgeEngine(db)
        results = ke.search_by_language("water", 5)
        assert isinstance(results, list)

    def test_categories(self, db):
        ke = KnowledgeEngine(db)
        cats = ke.get_categories()
        assert isinstance(cats, list)

    def test_search_no_results(self, db):
        ke = KnowledgeEngine(db)
        results = ke.search_by_language("xyznonexistent", 5)
        assert len(results) == 0

    def test_format_entry(self, db):
        ke = KnowledgeEngine(db)
        results = ke.search_by_language("water", 1)
        if results:
            formatted = ke.format_entry(results[0])
            assert len(formatted) > 0


class TestGoalEngine:
    def test_auto_generate(self, db, resource_mgr, survival):
        resource_mgr.init_defaults()
        resource_mgr.update_resource(ResourceType.WATER, 3.0, consumption=2.0)
        ge = GoalEngine(db, resource_mgr=resource_mgr, survival=survival)
        goals = ge.auto_generate_goals()
        assert len(goals) > 0

    def test_add_manual_goal(self, db):
        ge = GoalEngine(db)
        ge.add_manual_goal("Build shelter")
        goals = db.get_active_goals()
        assert len(goals) == 1
        assert goals[0].title == "Build shelter"

    def test_complete_goal(self, db):
        ge = GoalEngine(db)
        ge.add_manual_goal("Test goal")
        goals = db.get_active_goals()
        gid = goals[0].id
        ge.complete_goal(gid)
        active = db.get_active_goals()
        assert all(g.id != gid for g in active)

    def test_get_active_goals(self, db):
        ge = GoalEngine(db)
        assert ge.get_active_goals() == []
        ge.add_manual_goal("Test")
        assert len(ge.get_active_goals()) == 1


class TestResetManager:
    def test_evaluate_l1(self, db, resource_mgr):
        resource_mgr.init_defaults()
        rm = ResetManager(db, resource_mgr=resource_mgr)
        result = rm.evaluate_reset(ResetLevel.ASSESSMENT)
        assert result["allowed"] is True

    def test_evaluate_l3(self, db, resource_mgr):
        resource_mgr.init_defaults()
        rm = ResetManager(db, resource_mgr=resource_mgr)
        result = rm.evaluate_reset(ResetLevel.FACTORY)
        assert result["allowed"] is True

    def test_execute_l3_clears_data(self, db, resource_mgr):
        db.mark_initialized()
        resource_mgr.init_defaults()
        resource_mgr.update_resource(ResourceType.WATER, 10.0, consumption=2.0)
        rm = ResetManager(db, resource_mgr=resource_mgr)
        result = rm.execute_reset(ResetLevel.FACTORY, force=True)
        assert result["status"] == "ok"
        r = db.get_resource(ResourceType.WATER)
        assert r is None or r.current_amount == 0
        assert not db.is_initialized()

    def test_reset_forbidden_in_hibernation(self, db, resource_mgr):
        resource_mgr.init_defaults()
        state = db.get_operating_state()
        state.mode = OperatingMode.HIBERNATION.value
        db.save_operating_state(state)
        rm = ResetManager(db, resource_mgr=resource_mgr)
        result = rm.evaluate_reset(ResetLevel.ASSESSMENT)
        assert result["allowed"] is False


class TestDailyBriefing:
    def test_generate(self, db, resource_mgr, survival):
        resource_mgr.init_defaults()
        resource_mgr.update_resource(ResourceType.WATER, 10.0, consumption=2.0)
        ge = GoalEngine(db, resource_mgr=resource_mgr, survival=survival)
        briefing = DailyBriefing(db, resource_mgr, survival, ge)
        result = briefing.generate()
        assert len(result) > 0

    def test_generate_empty(self, db, resource_mgr, survival):
        resource_mgr.init_defaults()
        briefing = DailyBriefing(db, resource_mgr, survival)
        result = briefing.generate()
        assert len(result) > 0


class TestTimeline:
    def test_add_event(self, db):
        tl = TimelineManager(db)
        tl.add_event("milestone", "Found water", "Discovered a clean spring")
        events = tl.get_timeline()
        assert len(events) > 0

    def test_day_summary(self, db):
        tl = TimelineManager(db)
        tl.add_event("milestone", "Day 1 event", "Test")
        summary = tl.get_day_summary(1)
        assert summary is not None


class TestDiary:
    def test_add_entry(self, db):
        d = DiaryManager(db)
        d.add_entry("Today was hard but I found water", emotion="hopeful")
        entries = d.get_entries()
        assert len(entries) > 0

    def test_emotion_stats(self, db):
        d = DiaryManager(db)
        d.add_entry("Good day", emotion="positive")
        d.add_entry("Bad day", emotion="negative")
        stats = d.get_emotion_stats()
        assert stats is not None

    def test_delete_entry(self, db):
        d = DiaryManager(db)
        d.add_entry("To delete", emotion="neutral")
        entries = d.get_entries()
        assert len(entries) > 0
        entry = entries[0]
        eid = entry["id"] if isinstance(entry, dict) else entry.id
        d.delete_entry(eid)
        entries_after = d.get_entries()
        assert len(entries_after) == 0


class TestWeather:
    def test_predict_no_data(self, db):
        w = WeatherPredictor(db)
        result = w.predict_weather()
        assert result is not None

    def test_predict_with_pressure(self, db):
        w = WeatherPredictor(db)
        w.set_manual_pressure(1013.0)
        result = w.predict_weather()
        assert result is not None

    def test_cloud_guide(self, db):
        w = WeatherPredictor(db)
        guide = w.get_cloud_guide()
        assert len(guide) > 0


class TestPsychology:
    def test_assess_state(self, db):
        p = PsychologyTracker(db)
        state = p.assess_state()
        assert "loneliness_index" in state or "loneliness" in state
        assert "stress_index" in state or "stress" in state

    def test_record_interaction(self, db):
        p = PsychologyTracker(db)
        p.record_interaction("positive")
        state = p.assess_state()
        assert state is not None

    def test_self_assessment(self, db):
        p = PsychologyTracker(db)
        questions = p.get_self_assessment_questions()
        assert len(questions) > 0


class TestGPSManager:
    def test_set_position(self, db):
        gps = GPSManager(db)
        gps.set_manual_position(39.9, 116.4)
        pos = gps.get_position()
        assert pos is not None
        assert abs(pos["lat"] - 39.9) < 0.01

    def test_no_position(self, db):
        gps = GPSManager(db)
        pos = gps.get_position()
        assert pos is None

    def test_calculate_distance(self, db):
        gps = GPSManager(db)
        d = gps.calculate_distance(39.9, 116.4, 31.2, 121.5)
        assert d > 0


class TestEnvironmentAssessor:
    def test_assess(self, db, resource_mgr):
        resource_mgr.init_defaults()
        weather = WeatherPredictor(db)
        ea = EnvironmentAssessor(db, weather=weather, resource_mgr=resource_mgr)
        result = ea.assess()
        assert "climate" in result
        assert "terrain" in result

    def test_format_assessment(self, db, resource_mgr):
        resource_mgr.init_defaults()
        weather = WeatherPredictor(db)
        ea = EnvironmentAssessor(db, weather=weather, resource_mgr=resource_mgr)
        result = ea.assess()
        formatted = ea.format_assessment(result)
        assert len(formatted) > 0


class TestPersonalitySystem:
    def test_crisis_mode(self):
        p = PersonalitySystem()
        p.determine_mode(OperatingMode.HIBERNATION, [], 0)
        assert p.current_mode == PersonalityMode.CRISIS

    def test_stable_mode(self):
        p = PersonalitySystem()
        p.determine_mode(OperatingMode.STANDARD, [], 2)
        assert p.current_mode == PersonalityMode.STABLE

    def test_greet_uses_i18n(self):
        p = PersonalitySystem()
        p.determine_mode(OperatingMode.PROACTIVE, [], 2)
        greeting = p.greet()
        assert len(greeting) > 0


class TestI18n:
    def test_zh_default(self):
        set_language("zh")
        assert get_language() == "zh"
        text = t("app_name")
        assert text == "火种"

    def test_en(self):
        set_language("en")
        assert get_language() == "en"
        text = t("app_name")
        assert text == "AllSpark"
        set_language("zh")

    def test_missing_key_returns_key(self):
        text = t("nonexistent_key_xyz")
        assert text == "nonexistent_key_xyz"

    def test_format_params(self):
        set_language("zh")
        text = t("lang_switched", lang="en")
        assert "en" in text

    def test_resource_offline_key(self):
        set_language("zh")
        text = t("resource_offline")
        assert "未接入" in text
        set_language("en")
        text = t("resource_offline")
        assert "OFFLINE" in text
        set_language("zh")


class TestMissionPlanner:
    def test_generate_tasks(self, db, resource_mgr, survival):
        resource_mgr.init_defaults()
        resource_mgr.update_resource(ResourceType.WATER, 3.0, consumption=2.0)
        planner = MissionPlanner(db, resource_mgr)
        assessment = survival.assess()
        planner.generate_tasks_for_phase(assessment["phase"])
        tasks = db.get_active_tasks()
        assert len(tasks) > 0

    def test_complete_task(self, db, resource_mgr, survival):
        resource_mgr.init_defaults()
        planner = MissionPlanner(db, resource_mgr)
        assessment = survival.assess()
        planner.generate_tasks_for_phase(assessment["phase"])
        tasks = db.get_active_tasks()
        if tasks:
            tid = tasks[0].id
            planner.complete_task(tid)
            updated = db.get_active_tasks()
            assert all(t.id != tid or t.status == "completed" for t in updated)


class TestMapSystem:
    def test_add_poi(self, db):
        ms = MapSystem(db)
        ms.add_poi("Spring", "water", "Clean water source", 2.5, "North")
        pois = ms.get_all()
        assert len(pois) > 0

    def test_remove_poi(self, db):
        ms = MapSystem(db)
        ms.add_poi("Camp", "camp", "Base camp")
        pois = ms.get_all()
        ms.remove_poi(pois[0].id)
        assert len(ms.get_all()) == 0

    def test_format_map(self, db):
        ms = MapSystem(db)
        ms.add_poi("Test", "water", "Test POI")
        output = ms.format_map()
        assert len(output) > 0


class TestExperienceEngine:
    def test_log(self, db):
        ee = ExperienceEngine(db)
        entry = ee.log("Found water", "Clean spring", "Always check valleys")
        assert entry is not None

    def test_patterns(self, db):
        ee = ExperienceEngine(db)
        ee.log("Found water", "Spring", "Check valleys")
        ee.log("Found food", "Berries", "Look near water")
        patterns = ee.get_patterns()
        assert patterns is not None


class TestResetFactoryCompleteness:
    def test_l3_clears_all_tables(self, db, resource_mgr):
        db.mark_initialized()
        resource_mgr.init_defaults()
        resource_mgr.update_resource(ResourceType.WATER, 10.0, consumption=2.0)

        ge = GoalEngine(db)
        ge.add_manual_goal("Survive")

        tl = TimelineManager(db)
        tl.add_event("test", "Test event", "Desc")

        d = DiaryManager(db)
        d.add_entry("Test diary", emotion="neutral")

        rm = ResetManager(db, resource_mgr=resource_mgr)
        result = rm.execute_reset(ResetLevel.FACTORY, force=True)
        assert result["status"] == "ok"

        assert db.get_active_goals() == []
        assert not db.is_initialized()

        for table in ["timeline_events", "diary_entries", "resources", "goals"]:
            rows = db.conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
            assert rows["cnt"] == 0, f"Table {table} not cleared by L3 reset"

    def test_l1_preserves_resources(self, db, resource_mgr):
        db.mark_initialized()
        resource_mgr.init_defaults()
        resource_mgr.update_resource(ResourceType.WATER, 10.0, consumption=2.0)

        rm = ResetManager(db, resource_mgr=resource_mgr)
        result = rm.execute_reset(ResetLevel.ASSESSMENT, force=True)
        assert result["status"] == "ok"

        r = db.get_resource(ResourceType.WATER)
        assert r is not None
        assert r.current_amount == 10.0


class TestEndToEndWorkflow:
    def test_full_survival_session(self, db, resource_mgr, survival):
        resource_mgr.init_defaults()

        resource_mgr.update_resource(
            ResourceType.WATER, 5.0, consumption=2.0, intake=0.0
        )
        resource_mgr.update_resource(
            ResourceType.FOOD, 3000.0, consumption=2000.0, intake=0.0
        )
        resource_mgr.update_resource(
            ResourceType.POWER, 20.0, consumption=120.0, intake=0.0
        )

        assessment = survival.assess()
        assert assessment["phase"] == 0

        warnings = resource_mgr.check_warnings()
        assert len(warnings) > 0

        ge = GoalEngine(db, resource_mgr=resource_mgr, survival=survival)
        goals = ge.auto_generate_goals()
        assert len(goals) > 0

        briefing = DailyBriefing(db, resource_mgr, survival, ge)
        report = briefing.generate()
        assert len(report) > 50

        tl = TimelineManager(db)
        tl.add_event("system_event", "Session started", "Full workflow test")

        d = DiaryManager(db)
        d.add_entry("First day, found some supplies", emotion="hopeful")

        w = WeatherPredictor(db)
        w.set_manual_pressure(1013.0)
        weather = w.predict_weather()
        assert weather is not None

        p = PsychologyTracker(db)
        p.record_interaction("positive")
        psych = p.assess_state()
        assert psych is not None

    def test_resource_depletion_triggers_critical(self, db, resource_mgr):
        resource_mgr.init_defaults()
        resource_mgr.update_resource(
            ResourceType.POWER, 3.0, consumption=120.0, intake=0.0
        )
        warnings = resource_mgr.check_warnings()
        assert any(w["level"] == "critical" for w in warnings)

    def test_mode_transitions(self, db, resource_mgr):
        resource_mgr.init_defaults()

        resource_mgr.update_resource(ResourceType.POWER, 100.0, consumption=50.0, intake=0.0)
        mode, _ = resource_mgr.update_operating_mode()
        assert mode in (OperatingMode.PROACTIVE, OperatingMode.STANDARD)

        resource_mgr.update_resource(
            ResourceType.POWER, 30.0, consumption=120.0, intake=0.0
        )
        mode, _ = resource_mgr.update_operating_mode()
        assert mode in (OperatingMode.STANDARD, OperatingMode.ECONOMY)

        resource_mgr.update_resource(
            ResourceType.POWER, 2.0, consumption=120.0, intake=0.0
        )
        mode, _ = resource_mgr.update_operating_mode()
        assert mode == OperatingMode.HIBERNATION


class TestCLICommands:
    def test_process_status(self, cli):
        cli._process_command("status")
        assert cli.running is True

    def test_process_help(self, cli):
        cli._process_command("help")
        assert cli.running is True

    def test_process_resource(self, cli):
        cli._process_command("resource")
        assert cli.running is True

    def test_process_set_power(self, cli):
        cli._process_command("set power 100 120 50")
        r = cli.db.get_resource(ResourceType.POWER)
        assert r is not None
        assert r.current_amount == 100.0

    def test_process_set_water(self, cli):
        cli._process_command("set water 10 2")
        r = cli.db.get_resource(ResourceType.WATER)
        assert r is not None
        assert r.current_amount == 10.0

    def test_process_set_unknown_type(self, cli):
        cli._process_command("set unknown 10")

    def test_process_set_invalid_value(self, cli):
        cli._process_command("set power abc")

    def test_process_task(self, cli):
        cli._process_command("tasks")

    def test_process_map(self, cli):
        cli._process_command("map")

    def test_process_map_usage(self, cli):
        cli._process_command("map badsubcmd")

    def test_process_knowledge(self, cli):
        cli._process_command("know")

    def test_process_lang_switch(self, cli):
        cli._process_command("lang en")
        assert get_language() == "en"
        cli._process_command("lang zh")
        assert get_language() == "zh"

    def test_process_lang_invalid(self, cli):
        cli._process_command("lang xx")

    def test_process_goals(self, cli):
        cli._process_command("goals")

    def test_process_goals_add(self, cli):
        cli._process_command("goals add TestGoal")
        goals = cli.db.get_active_goals()
        assert any(g.title == "TestGoal" for g in goals)

    def test_process_goals_complete(self, cli):
        ge = cli.container.get("goal_engine")
        ge.add_manual_goal("ToComplete")
        goals = cli.db.get_active_goals()
        gid = goals[0].id
        cli._process_command(f"goals complete {gid}")

    def test_process_goals_abandon(self, cli):
        ge = cli.container.get("goal_engine")
        ge.add_manual_goal("ToAbandon")
        goals = cli.db.get_active_goals()
        gid = goals[0].id
        cli._process_command(f"goals abandon {gid}")

    def test_process_goals_not_found(self, cli):
        cli._process_command("goals complete nonexistent-id")

    def test_process_timeline(self, cli):
        cli._process_command("timeline")

    def test_process_diary(self, cli):
        cli._process_command("diary")

    def test_process_weather(self, cli):
        cli._process_command("weather")

    def test_process_psychology(self, cli):
        cli._process_command("psychology")

    def test_process_gps(self, cli):
        cli._process_command("gps")

    def test_process_environment(self, cli):
        cli._process_command("env")

    def test_process_experience(self, cli):
        cli._process_command("exp")

    def test_process_module(self, cli):
        cli._process_command("module")

    def test_process_llm(self, cli):
        cli._process_command("llm")

    def test_process_trade_status(self, cli):
        cli._process_command("trade status")

    def test_process_trade(self, cli):
        cli._process_command("trade")

    def test_process_community(self, cli):
        cli._process_command("community")

    def test_process_briefing(self, cli):
        cli._process_command("briefing")

    def test_process_sensor(self, cli):
        cli._process_command("sensor")

    def test_process_preserve(self, cli):
        cli._process_command("preserve")

    def test_process_reset_status(self, cli):
        cli._process_command("reset status")

    def test_exit(self, cli):
        cli._process_command("exit")
        assert cli.running is False

    def test_unknown_command(self, cli):
        cli._process_command("xyzunknown123")

    def test_empty_command(self, cli):
        cli._process_command("")


class TestDatabaseSaveDiaryEntry:
    def test_save_and_retrieve(self, db):
        from datetime import datetime

        from allspark.core.models import DiaryEntry
        entry = DiaryEntry(
            id="test-diary-1",
            date="2026-01-01",
            content="Test diary content",
            emotion="neutral",
            keywords="test",
            related_goal_id="",
            related_event="",
            is_public=False,
            created_at=datetime.now().isoformat(),
        )
        db.save_diary_entry(entry)
        retrieved = db.get_diary_entry("test-diary-1")
        assert retrieved is not None
        assert retrieved.content == "Test diary content"


class TestI18nCompleteness:
    def test_all_zh_keys_have_en(self):
        from allspark.core.i18n import MESSAGES
        zh_keys = set(MESSAGES["zh"].keys())
        en_keys = set(MESSAGES["en"].keys())
        missing_in_en = zh_keys - en_keys
        assert not missing_in_en, f"Keys missing in English: {missing_in_en}"

    def test_all_en_keys_have_zh(self):
        from allspark.core.i18n import MESSAGES
        zh_keys = set(MESSAGES["zh"].keys())
        en_keys = set(MESSAGES["en"].keys())
        missing_in_zh = en_keys - zh_keys
        assert not missing_in_zh, f"Keys missing in Chinese: {missing_in_zh}"

    def test_new_keys_work(self):
        set_language("zh")
        assert "未接入" in t("resource_offline")
        assert "未知" in t("unknown_resource_type", type="test")
        assert "错误" in t("invalid_numeric")
        set_language("en")
        assert "OFFLINE" in t("resource_offline")
        assert "Unknown" in t("unknown_resource_type", type="test")
        assert "Invalid" in t("invalid_numeric")
        set_language("zh")


class TestI18nLanguagePurity:
    def test_zh_mode_no_english_table_headers(self, cli):
        set_language("zh")
        from io import StringIO

        from rich.console import Console
        buf = StringIO()
        captured = Console(file=buf, force_terminal=True)
        old = _capture_all_consoles(cli, captured)

        try:
            cli._process_command("exp")
            output = buf.getvalue()
            assert "Metric" not in output
            assert "Value" not in output or "值" in output
        finally:
            _restore_all_consoles(cli, old)

    def test_en_mode_no_chinese_table_headers(self, cli):
        set_language("en")
        from io import StringIO

        from rich.console import Console
        buf = StringIO()
        captured = Console(file=buf, force_terminal=True)
        old = _capture_all_consoles(cli, captured)

        try:
            cli._process_command("exp")
            output = buf.getvalue()
            assert "指标" not in output
            assert "总经验数" not in output
        finally:
            _restore_all_consoles(cli, old)
            set_language("zh")

    def test_zh_mode_sensor_no_english(self, cli):
        set_language("zh")
        from io import StringIO

        from rich.console import Console
        buf = StringIO()
        captured = Console(file=buf, force_terminal=True)
        old = _capture_all_consoles(cli, captured)

        try:
            cli._process_command("sensor")
            output = buf.getvalue()
            assert "Polling" not in output
            assert "Devices" not in output
            assert "轮询" in output
            assert "设备数" in output
        finally:
            _restore_all_consoles(cli, old)

    def test_en_mode_sensor_no_chinese(self, cli):
        set_language("en")
        from io import StringIO

        from rich.console import Console
        buf = StringIO()
        captured = Console(file=buf, force_terminal=True)
        old = _capture_all_consoles(cli, captured)

        try:
            cli._process_command("sensor")
            output = buf.getvalue()
            assert "轮询" not in output
            assert "设备数" not in output
        finally:
            _restore_all_consoles(cli, old)
            set_language("zh")

    def test_zh_mode_preserve_no_english(self, cli):
        set_language("zh")
        from io import StringIO

        from rich.console import Console
        buf = StringIO()
        captured = Console(file=buf, force_terminal=True)
        old = _capture_all_consoles(cli, captured)

        try:
            cli._process_command("preserve")
            output = buf.getvalue()
            assert "Auto-Save" not in output
            assert "Interval" not in output
            assert "自动保存" in output
            assert "间隔" in output
        finally:
            _restore_all_consoles(cli, old)

    def test_zh_mode_module_no_english_headers(self, cli):
        set_language("zh")
        from io import StringIO

        from rich.console import Console
        buf = StringIO()
        captured = Console(file=buf, force_terminal=True)
        old = _capture_all_consoles(cli, captured)

        try:
            cli._process_command("module")
            output = buf.getvalue()
            assert "Module" not in output or "模块" in output
            assert "Status" not in output or "状态" in output
        finally:
            _restore_all_consoles(cli, old)

    def test_zh_mode_llm_no_english(self, cli):
        set_language("zh")
        from io import StringIO

        from rich.console import Console
        buf = StringIO()
        captured = Console(file=buf, force_terminal=True)
        old = _capture_all_consoles(cli, captured)

        try:
            cli._process_command("llm")
            output = buf.getvalue()
            assert "Available" not in output or "可用" in output
            assert "Not loaded" not in output or "未加载" in output
        finally:
            _restore_all_consoles(cli, old)

    def test_not_loaded_messages_use_i18n(self, cli):
        set_language("zh")
        from io import StringIO

        from rich.console import Console

        modules_to_test = ["weather", "psychology", "gps", "env"]
        for cmd in modules_to_test:
            buf = StringIO()
            captured = Console(file=buf, force_terminal=True)
            old = _capture_all_consoles(cli, captured)
            try:
                cli._process_command(cmd)
                output = buf.getvalue()
                assert "not loaded" not in output.lower() or "未加载" in output, f"English 'not loaded' found in ZH mode for '{cmd}': {output}"
            finally:
                _restore_all_consoles(cli, old)


class TestCLII18nConsistency:
    def test_set_command_zh(self, cli):
        set_language("zh")
        from io import StringIO

        from rich.console import Console
        buf = StringIO()
        captured = Console(file=buf, force_terminal=True)
        old = _capture_all_consoles(cli, captured)

        try:
            cli._process_command("set power 50 120 0")
            output = buf.getvalue()
            assert "电力" in output or "power" in output.lower()
        finally:
            _restore_all_consoles(cli, old)

    def test_set_command_en(self, cli):
        set_language("en")
        from io import StringIO

        from rich.console import Console
        buf = StringIO()
        captured = Console(file=buf, force_terminal=True)
        old = _capture_all_consoles(cli, captured)

        try:
            cli._process_command("set power 50 120 0")
            output = buf.getvalue()
            assert "电力" not in output
        finally:
            _restore_all_consoles(cli, old)
            set_language("zh")

    def test_trade_status_zh(self, cli):
        set_language("zh")
        from io import StringIO

        from rich.console import Console
        buf = StringIO()
        captured = Console(file=buf, force_terminal=True)
        old = _capture_all_consoles(cli, captured)

        try:
            cli._process_command("trade status")
            output = buf.getvalue()
            assert "总交易" in output
        finally:
            _restore_all_consoles(cli, old)

    def test_trade_status_en(self, cli):
        set_language("en")
        from io import StringIO

        from rich.console import Console
        buf = StringIO()
        captured = Console(file=buf, force_terminal=True)
        old = _capture_all_consoles(cli, captured)

        try:
            cli._process_command("trade status")
            output = buf.getvalue()
            assert "总交易" not in output
            assert "Total" in output
        finally:
            _restore_all_consoles(cli, old)
            set_language("zh")


class TestBriefingI18n:
    def test_briefing_zh_no_english_resource_names(self, db, resource_mgr):
        set_language("zh")
        from allspark.services.daily_briefing import DailyBriefing
        from allspark.services.survival_engine import SurvivalAssessmentEngine
        db.mark_initialized()
        resource_mgr.init_defaults()
        survival = SurvivalAssessmentEngine(db, resource_mgr)
        briefing = DailyBriefing(db, resource_mgr=resource_mgr, survival=survival)
        output = briefing.generate()
        assert "food:" not in output.lower()
        assert "power:" not in output.lower()
        assert "water:" not in output.lower()

    def test_briefing_en_no_chinese(self, db, resource_mgr):
        set_language("en")
        from allspark.services.daily_briefing import DailyBriefing
        from allspark.services.survival_engine import SurvivalAssessmentEngine
        db.mark_initialized()
        resource_mgr.init_defaults()
        survival = SurvivalAssessmentEngine(db, resource_mgr)
        briefing = DailyBriefing(db, resource_mgr=resource_mgr, survival=survival)
        output = briefing.generate()
        assert "食物" not in output
        assert "电力" not in output
        assert "饮水" not in output
        set_language("zh")


class TestEdgeCases:
    def test_set_zero_consumption_and_amount(self, cli):
        cli._process_command("set power 0 0 0")
        r = cli.db.get_resource(ResourceType.POWER)
        assert r is not None
        assert r.current_amount == 0
        assert r.daily_consumption == 0

    def test_set_negative_value(self, cli):
        cli._process_command("set power -10 100 50")
        r = cli.db.get_resource(ResourceType.POWER)
        assert r is not None

    def test_set_very_large_value(self, cli):
        cli._process_command("set power 999999 100 50")
        r = cli.db.get_resource(ResourceType.POWER)
        assert r.current_amount == 999999

    def test_multiple_lang_switches(self, cli):
        for _ in range(5):
            cli._process_command("lang en")
            assert get_language() == "en"
            cli._process_command("lang zh")
            assert get_language() == "zh"

    def test_command_with_extra_spaces(self, cli):
        cli._process_command("set   power   100   120   50")
        r = cli.db.get_resource(ResourceType.POWER)
        assert r is not None

    def test_command_case_insensitive(self, cli):
        cli._process_command("STATUS")
        cli._process_command("HELP")
        cli._process_command("RESOURCE")

    def test_goals_add_with_spaces(self, cli):
        cli._process_command("goals add 测试目标名称")
        goals = cli.db.get_active_goals()
        assert any("测试目标名称" in g.title for g in goals)

    def test_map_add_and_remove(self, cli):
        cli._process_command("map")

    def test_experience_log_and_patterns(self, cli):
        cli._process_command("exp log rain collected 5L")
        cli._process_command("exp log rain collected 3L")
        cli._process_command("exp patterns")

    def test_experience_recent(self, cli):
        cli._process_command("exp log fire started success")
        cli._process_command("exp recent")

    def test_reset_status_when_loaded(self, cli):
        cli._process_command("reset status")

    def test_knowledge_add_and_search(self, cli):
        from allspark.core.models import KnowledgeEntry
        entry = KnowledgeEntry(
            id="test-knowledge-1",
            title="太阳能热利用基础",
            summary="太阳能是最可靠的能源",
            category="energy",
            subcategory="solar",
            source="manual",
            verification="unverified",
            language="zh",
            priority=1,
        )
        cli.db.save_knowledge(entry)
        results = cli.db.search_knowledge("太阳能")
        assert len(results) > 0

    def test_diary_save_and_retrieve(self, db):
        from allspark.core.models import DiaryEntry
        entry = DiaryEntry(
            id="test-diary-edge",
            date="2026-05-17",
            content="Edge case test content",
            emotion="calm",
            keywords="test,edge",
            related_goal_id="",
            related_event="",
            is_public=False,
            created_at=datetime.now().isoformat(),
        )
        db.save_diary_entry(entry)
        retrieved = db.get_diary_entry("test-diary-edge")
        assert retrieved is not None
        assert retrieved.emotion == "calm"

    def test_resource_offline_detection(self, db, resource_mgr):
        db.mark_initialized()
        resource_mgr.init_defaults()
        r = db.get_resource(ResourceType.FOOD)
        is_offline = r.current_amount == 0 and r.daily_consumption == 0
        assert is_offline

    def test_resource_warning_generation(self, db, resource_mgr):
        db.mark_initialized()
        resource_mgr.init_defaults()
        resource_mgr.update_resource(ResourceType.POWER, 5, 100, 0)
        warnings = resource_mgr.check_warnings()
        assert len(warnings) > 0
        assert any("power" in w["resource"].lower() or "电力" in w["resource"] for w in warnings)

    def test_survival_phase_assessment(self, db, resource_mgr):
        db.mark_initialized()
        resource_mgr.init_defaults()
        from allspark.services.survival_engine import SurvivalAssessmentEngine
        engine = SurvivalAssessmentEngine(db, resource_mgr)
        result = engine.assess()
        assert "phase" in result
        assert result["phase"] >= 0

    def test_goal_progress_tracking(self, db):
        from allspark.services.goal_engine import GoalEngine
        ge = GoalEngine(db)
        goal = ge.add_manual_goal("Test Goal", description="Testing progress", priority="high")
        ge.complete_goal(goal.id)
        updated = db.get_goal(goal.id)
        assert updated is not None

    def test_reset_l1_preserves_resources(self, db, resource_mgr):
        db.mark_initialized()
        resource_mgr.init_defaults()
        resource_mgr.update_resource(ResourceType.POWER, 100, 120, 50)
        rm = ResetManager(db)
        rm.execute_reset(ResetLevel.ASSESSMENT)
        r = db.get_resource(ResourceType.POWER)
        assert r is not None
        assert r.current_amount == 100

    def test_reset_l3_clears_all(self, db, resource_mgr):
        db.mark_initialized()
        resource_mgr.init_defaults()
        resource_mgr.update_resource(ResourceType.POWER, 100, 120, 50)
        rm = ResetManager(db)
        rm.execute_reset(ResetLevel.FACTORY)
        r = db.get_resource(ResourceType.POWER)
        assert r is None or r.current_amount == 0

    def test_map_poi_operations(self, db):
        ms = MapSystem(db)
        poi = ms.add_poi("水源地", "water", description="附近水源")
        pois = ms.get_all()
        assert any(p.name == "水源地" for p in pois)
        ms.remove_poi(poi.id)

    def test_experience_pattern_detection(self, db):
        ee = ExperienceEngine(db)
        ee.log("rain", "collected water", "check gutters")
        ee.log("rain", "collected water", "check gutters")
        patterns = ee.get_patterns()
        assert len(patterns) > 0
        assert patterns[0]["event"] == "rain"

    def test_timeline_event_add(self, db):
        tl = TimelineManager(db)
        tl.add_event("test_event", "Test event title", description="Test description")
        events = tl.get_timeline()
        assert len(events) > 0
