"""SHA-251: initialization is recoverable and publishes only after bootstrap."""

import sqlite3
import threading
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from allspark.adapters import cli as cli_mod
from allspark.adapters import web_ui as wui
from allspark.adapters.cli import SparkCLI
from allspark.bootstrap import ApplicationBootstrap, PreparedApplication, prepare_application
from allspark.container import ServiceContainer
from allspark.core.database import Database
from allspark.core.i18n import get_language, set_language
from allspark.infrastructure.hardware import FeatureFlags
from allspark.services.initial_assessment import validate_initial_assessment
from allspark.services.resource_manager import ResourceManager
from allspark.services.survival_plan import SurvivalPlanService
from tests.assessment_helpers import valid_initial_assessment


class _ConnectionProxy:
    """Delegate SQLite operations while exposing deterministic failure evidence."""

    def __init__(self, connection, *, fail_next_commit=False):
        self.connection = connection
        self.fail_next_commit = fail_next_commit
        self.rollback_calls = 0

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def __enter__(self):
        self.connection.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None and self.fail_next_commit:
            self.fail_next_commit = False
            self.connection.rollback()
            raise sqlite3.OperationalError("commit failed after write")
        return self.connection.__exit__(exc_type, exc_value, traceback)

    def execute(self, *args, **kwargs):
        return self.connection.execute(*args, **kwargs)

    def commit(self):
        if self.fail_next_commit:
            self.fail_next_commit = False
            raise sqlite3.OperationalError("commit failed after write")
        return self.connection.commit()

    def rollback(self):
        self.rollback_calls += 1
        return self.connection.rollback()


def _candidate(db: Database | None = None) -> PreparedApplication:
    container = ServiceContainer()
    container.register("initial_assessment", MagicMock())
    if db is not None:
        container.register(
            "survival_plan", SurvivalPlanService(db, ResourceManager(db))
        )
    return PreparedApplication(
        bootstrap=SimpleNamespace(shutdown=MagicMock()),
        container=container,
        engine=MagicMock(name="rule_engine"),
    )


def _web_payload(client: TestClient, assessment: dict | None = None) -> dict:
    assessment = deepcopy(assessment or valid_initial_assessment())
    preview = client.post(
        "/api/init/assessment/preview",
        json={"language": "en", "assessment": assessment},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assessment["as_of"] = body["summary"]["as_of"]
    assessment["confirmed"] = True
    return {
        "language": "en",
        "assessment": assessment,
        "plan_id": body["plan"]["id"],
        "primary_action_id": body["plan"]["primary_candidate_ids"][0],
    }


def _cli_result(db: Database) -> dict:
    assessment = validate_initial_assessment(valid_initial_assessment())
    plan_service = SurvivalPlanService(db, ResourceManager(db))
    plan = plan_service.generate(assessment)
    return {
        "language": "en",
        "hardware": {"flags": MagicMock()},
        "assessment": assessment,
        "plan_id": plan.id,
        "primary_action_id": plan_service.primary_candidate_ids(plan)[0],
    }


def test_finalize_initialization_commits_language_and_marker_together(tmp_path) -> None:
    db = Database(tmp_path / "finalize.db")
    try:
        db.finalize_initialization("en")
        rows = db.conn.execute(
            "SELECT key, value FROM operating_state WHERE key IN ('language', 'initialized')"
        ).fetchall()
        assert {row["key"]: row["value"] for row in rows} == {
            "language": "en",
            "initialized": "true",
        }
    finally:
        db.close()


def test_finalize_initialization_rolls_back_both_keys_on_marker_failure(tmp_path) -> None:
    db = Database(tmp_path / "rollback.db")
    try:
        db.conn.execute(
            "INSERT INTO operating_state(key, value) VALUES ('language', 'zh')"
        )
        db.conn.execute(
            """
            CREATE TRIGGER reject_initialized
            BEFORE INSERT ON operating_state
            WHEN NEW.key = 'initialized'
            BEGIN
                SELECT RAISE(ABORT, 'marker failed');
            END
            """
        )
        db.conn.commit()

        with pytest.raises(sqlite3.IntegrityError, match="marker failed"):
            db.finalize_initialization("en")

        language = db.conn.execute(
            "SELECT value FROM operating_state WHERE key='language'"
        ).fetchone()
        assert language["value"] == "zh"
        assert db.is_initialized() is False
    finally:
        db.close()


def test_prepare_failure_cleans_candidate_and_retry_can_succeed(monkeypatch) -> None:
    failed_container = MagicMock()
    failed_container.require.side_effect = RuntimeError("rule engine missing")
    good_container = MagicMock()
    good_engine = object()
    good_container.require.return_value = good_engine

    first = SimpleNamespace(
        bootstrap=MagicMock(return_value=failed_container),
        shutdown=MagicMock(),
    )
    second = SimpleNamespace(
        bootstrap=MagicMock(return_value=good_container),
        shutdown=MagicMock(),
    )
    instances = iter((first, second))
    monkeypatch.setattr(
        "allspark.bootstrap.ApplicationBootstrap",
        lambda db, flags=None: next(instances),
    )

    failed_db = MagicMock()
    with pytest.raises(RuntimeError, match="rule engine missing"):
        prepare_application(failed_db)
    failed_db.conn.rollback.assert_called_once_with()
    first.shutdown.assert_called_once_with()

    prepared = prepare_application(MagicMock())
    assert prepared.container is good_container
    assert prepared.engine is good_engine
    second.shutdown.assert_not_called()


def test_prepare_preserves_original_error_when_rollback_and_cleanup_fail(
    monkeypatch,
) -> None:
    bootstrap = SimpleNamespace(
        bootstrap=MagicMock(side_effect=RuntimeError("original bootstrap failure")),
        shutdown=MagicMock(side_effect=RuntimeError("cleanup failure")),
    )
    db = MagicMock()
    db.conn.rollback.side_effect = sqlite3.OperationalError("rollback failure")
    monkeypatch.setattr(
        "allspark.bootstrap.ApplicationBootstrap",
        lambda db, flags=None: bootstrap,
    )

    with pytest.raises(RuntimeError, match="original bootstrap failure"):
        prepare_application(db)
    db.conn.rollback.assert_called_once_with()
    bootstrap.shutdown.assert_called_once_with()


def test_real_knowledge_stage_failure_rolls_back_cleans_and_retries(
    monkeypatch, tmp_path
) -> None:
    db = Database(tmp_path / "knowledge-stage.db")
    proxy = _ConnectionProxy(db.conn)
    db.conn = proxy
    original_load = ApplicationBootstrap._load_knowledge
    original_shutdown = ApplicationBootstrap.shutdown
    load_calls = 0
    shutdown_calls = 0

    def fail_real_stage_once(self):
        nonlocal load_calls
        load_calls += 1
        if load_calls == 1:
            raise RuntimeError("knowledge stage failed")
        return original_load(self)

    def track_shutdown(self):
        nonlocal shutdown_calls
        shutdown_calls += 1
        return original_shutdown(self)

    monkeypatch.setattr(ApplicationBootstrap, "_load_knowledge", fail_real_stage_once)
    monkeypatch.setattr(ApplicationBootstrap, "shutdown", track_shutdown)
    try:
        with pytest.raises(RuntimeError, match="knowledge stage failed"):
            prepare_application(db, flags=FeatureFlags())
        assert proxy.rollback_calls == 1
        assert shutdown_calls == 1
        assert db.is_initialized() is False

        prepared = prepare_application(db, flags=FeatureFlags())
        assert prepared.engine is not None
        assert load_calls == 2
    finally:
        db.close()


def test_candidate_shutdown_only_touches_instantiated_runtime_services() -> None:
    scheduler = MagicMock()
    docker = MagicMock()
    container = MagicMock()
    container.all_services.return_value = {
        "scheduler": scheduler,
        "docker_manager": docker,
    }
    bootstrap = ApplicationBootstrap.__new__(ApplicationBootstrap)
    bootstrap.container = container

    bootstrap.shutdown()

    container.all_services.assert_called_once_with()
    scheduler.stop.assert_called_once_with()
    docker.stop_all.assert_called_once_with()
    container.get.assert_not_called()


@pytest.mark.parametrize("failure_stage", ["draft", "prepare", "finalize"])
def test_web_init_failure_is_unpublished_cookie_free_and_retryable(
    monkeypatch, tmp_path, failure_stage
) -> None:
    original_language = get_language()
    set_language("en", persist=False)
    client = TestClient(wui.create_app(str(tmp_path / f"web-{failure_stage}.db"), token="secret"))
    assert client.post("/api/auth/login", json={"token": "secret"}).status_code == 200
    app = client.app
    db = app.state.db
    candidates: list[PreparedApplication] = []
    prepare_calls = 0

    def prepare(*args, **kwargs):
        nonlocal prepare_calls
        prepare_calls += 1
        if failure_stage == "prepare" and prepare_calls == 1:
            raise RuntimeError("knowledge/bootstrap failed")
        candidate = _candidate(db)
        candidates.append(candidate)
        return candidate

    monkeypatch.setattr(wui, "_prepare_engine", prepare)

    if failure_stage == "draft":
        original_save = db.save_survivor_state
        failed = False

        def fail_draft_once(key, value, *, commit=True):
            nonlocal failed
            if key == "language" and not failed:
                failed = True
                raise RuntimeError("draft failed")
            return original_save(key, value, commit=commit)

        monkeypatch.setattr(db, "save_survivor_state", fail_draft_once)
    elif failure_stage == "finalize":
        original_finalize = db.finalize_initialization
        failed = False

        def fail_finalize_once(
            language, plan_id=None, accepted_action_id=None, *, commit=True
        ):
            nonlocal failed
            if not failed:
                failed = True
                raise sqlite3.OperationalError("finalize failed")
            return original_finalize(
                language, plan_id, accepted_action_id, commit=commit
            )

        monkeypatch.setattr(db, "finalize_initialization", fail_finalize_once)

    payload = _web_payload(client)
    payload.update({"language": "zh", "survivor_name": "Retry Survivor"})
    try:
        failed_response = client.post("/api/init/complete", json=payload)
        assert failed_response.status_code == 503
        assert failed_response.json()["error"] == "bootstrap_failed"
        assert "set-cookie" not in failed_response.headers
        assert db.is_initialized() is False
        assert app.state.initialized is False
        assert app.state.container is None
        assert app.state.engine is None
        assert get_language() == "en"

        retry = client.post("/api/init/complete", json=payload)
        assert retry.status_code == 200, retry.text
        assert db.is_initialized() is True
        assert app.state.initialized is True
        assert app.state.container is candidates[-1].container
        assert app.state.engine is candidates[-1].engine
        assert db.get_survivor_state()["name"] == "Retry Survivor"

        if failure_stage == "finalize":
            candidates[0].bootstrap.shutdown.assert_called_once_with()
    finally:
        set_language(original_language, persist=False)


def test_web_concurrent_init_bootstraps_at_most_once(monkeypatch, tmp_path) -> None:
    client = TestClient(wui.create_app(str(tmp_path / "concurrent.db")))
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def blocking_prepare(*args, **kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(timeout=5)
        return _candidate(client.app.state.db)

    monkeypatch.setattr(wui, "_prepare_engine", blocking_prepare)
    first_response = []

    payload = _web_payload(client)
    payload["language"] = "zh"

    def first_request():
        first_response.append(
            client.post("/api/init/complete", json=payload)
        )

    thread = threading.Thread(target=first_request)
    thread.start()
    assert entered.wait(timeout=5)
    second = client.post("/api/init/complete", json=payload)
    release.set()
    thread.join(timeout=5)

    assert second.status_code == 409
    assert second.json()["error"] == "bootstrap_in_progress"
    assert [response.status_code for response in first_response] == [200]
    assert calls == 1


def test_web_rejects_invalid_language_before_any_draft_write(
    monkeypatch, tmp_path
) -> None:
    client = TestClient(wui.create_app(str(tmp_path / "invalid-language.db")))
    monkeypatch.setattr(
        wui,
        "detect_hardware",
        lambda: pytest.fail("invalid language must fail before hardware draft"),
    )

    response = client.post(
        "/api/init/complete",
        json={"language": "fr", "survivor_name": "Must Not Persist"},
    )

    assert response.status_code == 422
    assert response.json()["error"] == "invalid_language"
    db = client.app.state.db
    assert db.is_initialized() is False
    assert db.get_survivor_state() == {}
    assert db.get_hardware_profile() == {}
    assert client.app.state.container is None
    assert client.app.state.engine is None


def test_web_commit_after_write_failure_rolls_back_before_retry(
    monkeypatch, tmp_path
) -> None:
    client = TestClient(wui.create_app(str(tmp_path / "commit-retry.db")))
    db = client.app.state.db
    proxy = _ConnectionProxy(db.conn, fail_next_commit=True)
    db.conn = proxy
    candidates: list[PreparedApplication] = []

    def prepare(*args, **kwargs):
        candidate = _candidate(db)
        candidates.append(candidate)
        return candidate

    monkeypatch.setattr(wui, "_prepare_engine", prepare)
    payload = _web_payload(client)
    payload["survivor_name"] = "Commit Retry"

    failed = client.post("/api/init/complete", json=payload)
    assert failed.status_code == 503
    assert proxy.rollback_calls == 1
    assert db.is_initialized() is False
    assert db.get_hardware_profile() == {}
    assert client.app.state.container is None

    retry = client.post("/api/init/complete", json=payload)
    assert retry.status_code == 200
    assert db.is_initialized() is True
    assert candidates[0].bootstrap.shutdown.call_count == 1
    assert client.app.state.container is candidates[-1].container


def test_cli_finalize_failure_keeps_runtime_unpublished_and_retry_succeeds(
    monkeypatch, tmp_path
) -> None:
    cli = SparkCLI(str(tmp_path / "cli.db"))
    cli.running = False
    flags = MagicMock()
    wizard_calls = 0
    candidates: list[PreparedApplication] = []

    def wizard(db):
        nonlocal wizard_calls
        wizard_calls += 1
        set_language("en", persist=False)
        result = _cli_result(db)
        result["hardware"] = {"flags": flags}
        return result

    def prepare(db, flags=None):
        candidate = _candidate(db)
        candidates.append(candidate)
        return candidate

    monkeypatch.setattr(cli_mod, "run_init_wizard", wizard)
    monkeypatch.setattr(cli_mod, "prepare_application", prepare)
    monkeypatch.setattr(cli, "_setup_dispatcher", lambda: None)
    monkeypatch.setattr(cli, "_print_banner", lambda: None)
    monkeypatch.setattr(cli, "_print_initial_status", lambda: None)
    cli.db.save_initialization_draft(
        {
            "language": "en",
            "step": 2,
            "assessment": {},
            "selected_primary_action_id": None,
        },
        source="web",
        expected_revision=0,
    )
    original_finalize = cli.db.finalize_initialization
    finalize_calls = 0

    def fail_finalize_once(
        language, plan_id=None, accepted_action_id=None, *, commit=True
    ):
        nonlocal finalize_calls
        finalize_calls += 1
        if finalize_calls == 1:
            raise sqlite3.OperationalError("finalize failed")
        return original_finalize(
            language, plan_id, accepted_action_id, commit=commit
        )

    monkeypatch.setattr(cli.db, "finalize_initialization", fail_finalize_once)

    with pytest.raises(sqlite3.OperationalError, match="finalize failed"):
        cli.run()
    assert cli.db.is_initialized() is False
    assert cli._container is None
    assert cli._engine is None
    assert cli.db.get_initialization_draft() is not None
    candidates[0].bootstrap.shutdown.assert_called_once_with()

    cli.run()
    assert cli.db.is_initialized() is True
    assert cli._container is candidates[1].container
    assert cli._engine is candidates[1].engine
    assert cli.db.get_initialization_draft() is None
    assert wizard_calls == 2
    cli.db.close()


def test_cli_commit_after_write_failure_rolls_back_before_retry(
    monkeypatch, tmp_path
) -> None:
    cli = SparkCLI(str(tmp_path / "cli-commit.db"))
    cli.running = False
    proxy = _ConnectionProxy(cli.db.conn, fail_next_commit=True)
    cli.db.conn = proxy
    candidate = _candidate(cli.db)
    wizard_calls = 0

    def wizard(db):
        nonlocal wizard_calls
        wizard_calls += 1
        db.save_survivor_state("name", "CLI Retry")
        return _cli_result(db)

    monkeypatch.setattr(cli_mod, "run_init_wizard", wizard)
    monkeypatch.setattr(cli_mod, "prepare_application", lambda *a, **k: candidate)
    monkeypatch.setattr(cli, "_setup_dispatcher", lambda: None)
    monkeypatch.setattr(cli, "_print_banner", lambda: None)
    monkeypatch.setattr(cli, "_print_initial_status", lambda: None)

    with pytest.raises(sqlite3.OperationalError, match="commit failed after write"):
        cli.run()
    assert proxy.rollback_calls == 1
    assert cli.db.get_survivor_state() == {}
    assert cli.db.is_initialized() is False
    assert cli._container is None

    cli.run()
    assert cli.db.is_initialized() is True
    assert cli._container is candidate.container
    assert cli.db.get_survivor_state()["name"] == "Survivor"
    assert wizard_calls == 2
    cli.db.close()
