"""SHA-155: CLI cold start must not leak i18n markers or dependency debug logs.

Goal titles are persisted as markers (mark("goal_agriculture_title")); the CLI
must render() them before display. Dependency degradation (jieba, VectorEngine
fallback) must not pollute the interactive first screen.
"""
from io import StringIO

from rich.console import Console

from allspark.adapters import cli as cli_mod
from allspark.adapters.cli import SparkCLI
from allspark.bootstrap import ApplicationBootstrap
from allspark.core.database import Database
from allspark.core.i18n import mark, render, set_language
from allspark.infrastructure.hardware import FeatureFlags
from allspark.services.rule_engine import RuleEngine


def _build_cli(db):
    cli_obj = SparkCLI.__new__(SparkCLI)
    cli_obj.db = db
    flags = FeatureFlags()
    cli_obj.container = ApplicationBootstrap(db, flags=flags).bootstrap()
    cli_obj.engine = RuleEngine(cli_obj.container)
    cli_obj.running = True
    cli_obj._flags = flags
    cli_obj._dispatcher = None
    return cli_obj


def _capture():
    buf = StringIO()
    cap = Console(file=buf, force_terminal=True)
    old = cli_mod.console
    cli_mod.console = cap
    return buf, old


class TestMarkerRendering:
    def test_goal_marker_renders_translated_zh(self):
        set_language("zh")
        rendered = render(mark("goal_agriculture_title"))
        assert "t:" not in rendered
        assert "goal_" not in rendered
        assert "农业" in rendered

    def test_goal_marker_renders_translated_en(self):
        set_language("en")
        rendered = render(mark("goal_agriculture_title"))
        assert "t:" not in rendered
        assert "goal_" not in rendered


class TestColdStartNoMarkerLeak:
    def _run_post_init(self, lang, tmp_path):
        set_language(lang)
        db = Database(tmp_path / f"cli_{lang}.db")
        db.mark_initialized()
        rm = None
        try:
            cli_obj = _build_cli(db)
            rm = cli_obj.container.get("resource_manager")
            if rm:
                rm.init_defaults()
            buf, old = _capture()
            try:
                cli_obj._phase7_post_init()
                return buf.getvalue()
            finally:
                cli_mod.console = old
        finally:
            db.close()

    def test_initialized_cold_start_zh_no_marker(self, tmp_path):
        output = self._run_post_init("zh", tmp_path)
        assert "t:" not in output, output
        assert "goal_" not in output, output  # no marker key leak

    def test_initialized_cold_start_en_no_marker(self, tmp_path):
        output = self._run_post_init("en", tmp_path)
        assert "t:" not in output, output
        assert "goal_" not in output, output


class TestLoggingNoise:
    def test_jieba_logger_suppressed(self):
        import logging

        from allspark.__main__ import _configure_logging

        _configure_logging()
        assert logging.getLogger("jieba").level >= logging.WARNING
