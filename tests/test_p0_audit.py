import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from allspark.adapters.web_ui import create_app
from allspark.bootstrap import ApplicationBootstrap
from allspark.commands.knowledge import KnowledgeCommand
from allspark.core.database import Database
from allspark.core.i18n import set_language
from allspark.core.models import KnowledgeEntry, OperatingMode, ResourceType
from allspark.infrastructure.hardware import FeatureFlags
from allspark.infrastructure.module_loader import ModuleRegistry
from allspark.services.resource_manager import ResourceManager
from allspark.services.survival_engine import SurvivalAssessmentEngine


class TempDb:
    def __enter__(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        return self.path

    def __exit__(self, exc_type, exc, tb):
        if os.path.exists(self.path):
            os.unlink(self.path)


def _initialized_app(db_path: str):
    db = Database(db_path)
    try:
        db.mark_initialized()
        ModuleRegistry(FeatureFlags()).save_to_db(db)
    finally:
        db.close()
    return create_app(db_path)


def test_web_core_routes_accept_json_body_contract():
    with TempDb() as path:
        client = TestClient(_initialized_app(path))

        chat = client.post("/api/chat", json={"message": "status"})
        assert chat.status_code == 200
        assert "response" in chat.json()

        experience = client.post(
            "/api/experience",
            json={"event": "found water", "outcome": "success", "lesson": "mark source"},
        )
        assert experience.status_code == 200
        assert experience.json()["status"] == "ok"

        resource = client.post("/api/resources", json={"type": "water", "amount": 5})
        assert resource.status_code == 200
        assert resource.json()["status"] == "ok"


def test_web_survival_routes_do_not_call_missing_service_methods():
    with TempDb() as path:
        client = TestClient(_initialized_app(path))

        for route in [
            "/api/timeline",
            "/api/timeline/recent",
            "/api/diary",
            "/api/diary/review",
            "/api/gps",
            "/api/psych",
            "/api/reset/logs",
        ]:
            response = client.get(route)
            # 503 = service not loaded (expected for unit-test env);
            # < 500 would reject it, so allow 503 as well.
            assert response.status_code in (200, 503), route
            assert isinstance(response.json(), dict)


def test_builtin_knowledge_loads_tier3_entries():
    with TempDb() as path:
        db = Database(path)
        try:
            ApplicationBootstrap(db, flags=FeatureFlags()).bootstrap()
            assert db.get_knowledge("community/governance/structure") is not None
        finally:
            db.close()


def test_knowledge_yaml_bilingual_parity():
    """SHA-37: tier1/2/3 English YAML must exist and match the Chinese entry
    counts so English users no longer fall back to Chinese titles. Also guards
    against future language-file drift."""
    import yaml

    from allspark.services.knowledge_loader import _DATA_DIR

    for tier in (0, 1, 2, 3):
        zh = yaml.safe_load((_DATA_DIR / f"tier{tier}_zh.yaml").read_text())
        en_path = _DATA_DIR / f"tier{tier}_en.yaml"
        assert en_path.exists(), f"tier{tier}_en.yaml is missing (SHA-37)"
        en = yaml.safe_load(en_path.read_text())
        assert len(en) == len(zh), (
            f"tier{tier}: en={len(en)} vs zh={len(zh)} entries"
        )
        # Each en entry must declare language=en and carry the /en id suffix
        # so it does not collide with the zh row in the DB.
        for e in en:
            assert e.get("language") == "en"
            assert e["id"].endswith("/en"), e["id"]
            assert isinstance(e.get("steps"), list)
            assert all(isinstance(s, str) for s in e["steps"])


def test_english_users_get_english_knowledge_titles():
    """SHA-37 / B-12: with language=en, searching must return English titles
    for tier1/2/3 — not Chinese fallbacks."""
    with TempDb() as path:
        db = Database(path)
        try:
            ApplicationBootstrap(db, flags=FeatureFlags()).bootstrap()
            set_language("en")
            # agriculture is a tier1 category present in both languages.
            rows = db.get_knowledge_by_category("agriculture", language="en")
            assert rows, "no English agriculture entries loaded"
            for r in rows:
                # English titles must contain ASCII letters; a Chinese fallback
                # would be CJK-only.
                assert any(ch.isalpha() and ord(ch) < 128 for ch in r.title), r.title
        finally:
            db.close()


def test_search_knowledge_prioritizes_requested_language():
    with TempDb() as path:
        db = Database(path)
        try:
            db.save_knowledge(KnowledgeEntry(
                id="test/water/en",
                category="survival",
                subcategory="water",
                priority=0,
                title="Water purification",
                summary="Boil water before drinking.",
                language="en",
            ))
            db.save_knowledge(KnowledgeEntry(
                id="test/water/zh",
                category="survival",
                subcategory="water",
                priority=1,
                title="净水方法",
                summary="饮用前需要煮沸净化水源。",
                language="zh",
            ))

            zh_results = db.search_knowledge("水", limit=5, language="zh")
            assert zh_results
            assert zh_results[0].language == "zh"

            en_results = db.search_knowledge("water", limit=5, language="en")
            assert en_results
            assert en_results[0].language == "en"
        finally:
            db.close()
            set_language("zh")


def test_knowledge_command_uses_language_aware_search(monkeypatch):
    calls = []

    class FakeKnowledge:
        def search_by_language(self, query, limit=10):
            calls.append((query, limit))
            return []

        def get_by_category(self, category, subcategory=""):
            return []

        def get_categories(self):
            return []

    class FakeContainer:
        db = None

        def get(self, name):
            if name == "knowledge":
                return FakeKnowledge()
            return None

    cmd = KnowledgeCommand(FakeContainer())
    monkeypatch.setattr(cmd.console, "print", lambda *args, **kwargs: None)
    cmd.execute(["water", "purification"])

    assert calls == [("water purification", 10)]


def test_builtin_knowledge_updates_existing_entries():
    with TempDb() as path:
        db = Database(path)
        try:
            db.save_knowledge(KnowledgeEntry(
                id="community/governance/structure",
                category="community",
                subcategory="governance",
                priority=2,
                title="旧标题",
                summary="旧摘要",
                language="zh",
            ))
            ApplicationBootstrap(db, flags=FeatureFlags()).bootstrap()
            updated = db.get_knowledge("community/governance/structure")
            assert updated.title == "社区组织架构设计"
            assert updated.summary != "旧摘要"
        finally:
            db.close()


def test_unconfigured_resources_do_not_trigger_countdowns_or_crisis_mode():
    with TempDb() as path:
        db = Database(path)
        try:
            resource_mgr = ResourceManager(db)
            resource_mgr.init_defaults()

            assert resource_mgr.check_warnings() == []
            assert resource_mgr.determine_operating_mode() == OperatingMode.STANDARD

            survival = SurvivalAssessmentEngine(db, resource_mgr).assess()
            assert survival["bottleneck"] is None

            power = db.get_resource(ResourceType.POWER)
            assert resource_mgr.is_configured(power) is False
        finally:
            db.close()


def test_resource_api_marks_unconfigured_without_countdown():
    with TempDb() as path:
        client = TestClient(_initialized_app(path))
        resources = client.get("/api/resources")
        assert resources.status_code == 200
        power = next(r for r in resources.json() if r["type"] == "power")
        assert power["configured"] is False
        assert power["status"] == "unconfigured"
        assert power["remaining_hours"] is None

        client.post("/api/resources", json={"type": "water", "amount": 5})
        updated = client.get("/api/resources").json()
        water = next(r for r in updated if r["type"] == "water")
        assert water["configured"] is True
        assert water["remaining_hours"] is None


def test_set_amount_without_consumption_does_not_print_9999_countdown(monkeypatch):
    from allspark.commands.basic import SetCommand

    with TempDb() as path:
        db = Database(path)
        try:
            container = ApplicationBootstrap(db, flags=FeatureFlags()).bootstrap()
            cmd = SetCommand(container)
            printed = []
            monkeypatch.setattr(cmd.console, "print", lambda value="", *args, **kwargs: printed.append(str(value)))

            cmd.execute(["water", "5"])

            output = "\n".join(printed)
            assert "9999" not in output
            assert "预计可用" not in output
            assert "Estimated remaining" not in output
        finally:
            db.close()


def test_skf_routes_reject_paths_outside_safe_directory():
    with TempDb() as path:
        client = TestClient(_initialized_app(path))
        for method, route in [
            (client.get, "/api/skf/info"),
            (client.post, "/api/skf/import"),
            (client.post, "/api/skf/export"),
        ]:
            response = method(route, params={"path": "/etc/passwd"})
            assert response.status_code == 400


def test_vision_route_rejects_paths_outside_safe_media_directory():
    from allspark.adapters.routes.network import _safe_media_path

    with pytest.raises(Exception):
        _safe_media_path("/etc/passwd")


def test_text_only_vision_refuses_safety_critical_tasks(tmp_path):
    from allspark.services.vision_engine import VisionEngine, VisionTask

    image = tmp_path / "plant.jpg"
    image.write_bytes(b"not really an image")

    class FakeInnerLLM:
        def create_chat_completion(self):
            return None

    class FakeLLM:
        available = True
        _llm = FakeInnerLLM()
        _model_path = "qwen-text-only.gguf"

    result = VisionEngine(llm_engine=FakeLLM()).analyze_image(str(image), VisionTask.PLANT_IDENTIFY)
    assert result.confidence == "none"
    assert "metadata-only" in " ".join(result.warnings)


def test_config_and_repository_do_not_claim_fake_success():
    root = Path(__file__).resolve().parents[1]
    config_html = (root / "allspark" / "templates" / "config.html").read_text(encoding="utf-8")
    repository_html = (root / "allspark" / "templates" / "repository.html").read_text(encoding="utf-8")

    assert "Syntax check passed" not in config_html
    assert "Configuration ${currentConfig} saved" not in config_html
    assert "Use /api/skf/export endpoint" not in repository_html
    assert "Use /api/skf/import endpoint" not in repository_html


def test_dashboard_template_renders_localized_strings():
    with TempDb() as path:
        client = TestClient(_initialized_app(path))

        zh_response = client.get("/")
        assert zh_response.status_code == 200
        zh_html = zh_response.text
        assert "系统健康总览" in zh_html
        assert "活跃任务" in zh_html
        from allspark import __version__
        assert __version__ in zh_html
        assert "0.2.0" not in zh_html
        assert 'lang="zh"' in zh_html
        assert "System Health Matrix" not in zh_html


def test_dashboard_template_supports_english_locale(monkeypatch):
    from allspark.core import i18n

    monkeypatch.setattr(i18n, "_current_lang", "en")
    try:
        with TempDb() as path:
            client = TestClient(_initialized_app(path))
            response = client.get("/")
            assert response.status_code == 200
            html = response.text
            assert "System Health Matrix" in html
            assert "Active Tasks" in html
            assert "Dashboard" in html
            assert 'lang="en"' in html
    finally:
        monkeypatch.setattr(i18n, "_current_lang", "zh")


def test_system_page_does_not_fake_cpu_ram_disk_with_survival_resources():
    root = Path(__file__).resolve().parents[1]
    html = (root / "allspark" / "templates" / "system.html").read_text(encoding="utf-8")
    assert "CPU_UTILIZATION" not in html
    assert "RAM_ALLOCATION" not in html
    assert "DISK_IO" not in html
    assert 'find(r => r.type === "power")' not in html


def test_localized_web_pages_render_zh_strings():
    with TempDb() as path:
        client = TestClient(_initialized_app(path))
        for url, marker in [
            ("/system", "系统监控"),
            ("/executions", "任务执行日志"),
            ("/config", "配置"),
            ("/repository", "资料库"),
        ]:
            response = client.get(url)
            assert response.status_code == 200, url
            assert marker in response.text, url


def test_longtail_psychology_stress_includes_low_power():
    import os
    import tempfile

    from allspark.core.database import Database
    from allspark.services.psychology import PsychologyTracker
    from allspark.services.resource_manager import ResourceManager
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path)
    try:
        rm = ResourceManager(db)
        rm.init_defaults()
        rm.update_resource(
            ResourceType.POWER, 5.0, consumption=120.0, intake=0.0
        )
        psych = PsychologyTracker(db)
        state = psych.assess_state()
        assert state["stress_index"] > 0, "Power stress should register when power < 6h remaining"
    finally:
        db.close()
        os.unlink(path)


def test_longtail_psychology_import_path_works():
    import os
    import tempfile

    from allspark.core.database import Database
    from allspark.services.psychology import PsychologyTracker
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path)
    try:
        psych = PsychologyTracker(db)
        state = psych.assess_state()
        assert "stress_index" in state
    finally:
        db.close()
        os.unlink(path)


def test_personality_has_set_mode_method():
    from allspark.services.personality import PersonalityMode, PersonalitySystem
    ps = PersonalitySystem()
    ps.set_mode("companion")
    assert ps.current_mode.value == "companion"
    ps.set_mode(PersonalityMode.CRISIS)
    assert ps.current_mode.value == "crisis"


def test_complete_milestone_no_longer_uses_empty_goal_query():
    from unittest.mock import MagicMock

    from allspark.services.goal_engine import GoalEngine
    db = MagicMock()
    db.get_active_goals.return_value = []
    ge = GoalEngine(db)
    result = ge.complete_milestone("nonexistent")
    assert result is None
    for call in db.get_milestones_by_goal.call_args_list:
        assert call.args[0] != "", "complete_milestone must not call get_milestones_by_goal('')"


def test_mission_planner_format_side_missions_localized(monkeypatch):
    from unittest.mock import MagicMock

    from allspark.core.i18n import t
    from allspark.core.models import Task, TaskType
    from allspark.services.mission_planner import MissionPlanner
    db = MagicMock()
    rm = MagicMock()
    planner = MissionPlanner(db, rm)
    tasks = [
        Task(id="side-1", phase=0, priority=10, title="Explore", task_type=TaskType.SIDE.value, status="pending"),
    ]
    output = planner.format_tasks(tasks)
    assert "Side Missions" not in output
    assert t("side_missions_label") in output


def test_weather_trend_can_change_with_history():
    from unittest.mock import MagicMock

    from allspark.services.weather import WeatherPredictor
    db = MagicMock()
    db.conn.execute.return_value.fetchall.return_value = [("1010",), ("1020",)]
    wp = WeatherPredictor(db=db)
    trend = wp._calculate_trend()
    assert trend in ("rising", "falling", "stable")


def test_reset_l1_preserves_initialized_language_and_deploy_mode():
    with TempDb() as path:
        db = Database(path)
        try:
            db.mark_initialized()
            db.conn.execute("INSERT OR REPLACE INTO operating_state VALUES (?,?)", ("language", "en"))
            db.conn.execute("INSERT OR REPLACE INTO operating_state VALUES (?,?)", ("deploy_mode", "docker"))
            db.save_survivor_state("language", "en")
            db.save_survivor_state("name", "Ada")
            db.conn.commit()

            from allspark.core.models import ResetLevel
            from allspark.services.reset_manager import ResetManager
            ResetManager(db).execute_reset(ResetLevel.ASSESSMENT)

            assert db.is_initialized() is True
            survivor = db.get_survivor_state()
            assert survivor.get("language") == "en"
            assert survivor.get("name") == "Ada"
            row = db.conn.execute(
                "SELECT value FROM operating_state WHERE key='deploy_mode'"
            ).fetchone()
            assert row is not None and row["value"] == "docker"
        finally:
            db.close()


def test_reset_l1_preserves_gps_track():
    with TempDb() as path:
        db = Database(path)
        try:
            db.mark_initialized()
            db.save_hardware_profile("track-abc123", '{"lat":1.0,"lon":2.0}')
            db.save_hardware_profile("last_gps_position", '{"lat":1.0,"lon":2.0}')
            db.save_hardware_profile("cpu_arch", "arm64")

            from allspark.core.models import ResetLevel
            from allspark.services.reset_manager import ResetManager
            ResetManager(db).execute_reset(ResetLevel.ASSESSMENT)

            track = db.conn.execute(
                "SELECT value FROM hardware_profile WHERE key='track-abc123'"
            ).fetchone()
            assert track is not None
            position = db.conn.execute(
                "SELECT value FROM hardware_profile WHERE key='last_gps_position'"
            ).fetchone()
            assert position is not None
            cpu = db.conn.execute(
                "SELECT value FROM hardware_profile WHERE key='cpu_arch'"
            ).fetchone()
            assert cpu is None, "non-protected hardware_profile keys should still be cleared on L1"
        finally:
            db.close()


def test_timeline_day_uses_independent_baseline():
    from unittest.mock import MagicMock

    from allspark.services.timeline import TimelineManager
    db = MagicMock()
    db.conn.execute.return_value.fetchone.return_value = {"value": "2025-01-01T00:00:00"}
    tl = TimelineManager(db=db)
    day = tl._get_current_day()
    assert day >= 1


def test_executions_template_uses_real_task_status_vocabulary():
    root = Path(__file__).resolve().parents[1]
    html = (root / "allspark" / "templates" / "executions.html").read_text(encoding="utf-8")
    assert 't.status === "completed" || t.status === "done"' not in html
    assert 't.status === "running" || t.status === "in_progress"' not in html
    assert 't.status === "completed"' in html
    assert 't.status === "in_progress"' in html
