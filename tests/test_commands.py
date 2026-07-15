"""Tests for the command layer: BaseCommand, CommandDispatcher, and all Command classes."""

from unittest.mock import MagicMock

import pytest

from allspark.commands.base import BaseCommand
from allspark.commands.dispatcher import CommandDispatcher, discover_commands
from allspark.core.database import Database
from allspark.core.i18n import set_language
from allspark.infrastructure.hardware import FeatureFlags

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "test.db"))


@pytest.fixture
def flags():
    return FeatureFlags()


@pytest.fixture
def container(db, flags):
    """Use ApplicationBootstrap to get a fully-wired ServiceContainer."""
    from allspark.bootstrap import ApplicationBootstrap
    bootstrap = ApplicationBootstrap(db, flags=flags)
    return bootstrap.bootstrap()


@pytest.fixture
def dispatcher(container):
    return CommandDispatcher(container)


# ─── BaseCommand Tests ───────────────────────────────────────────────────────


class TestBaseCommand:
    def test_command_name_default(self, container):
        cmd = BaseCommand(container)
        assert cmd.COMMAND_NAME == ""

    def test_aliases_default(self, container):
        cmd = BaseCommand(container)
        assert cmd.ALIASES == ()

    def test_match_by_name(self, container):
        cmd = BaseCommand(container)
        cmd.COMMAND_NAME = "test"
        assert cmd.match("test") is True

    def test_match_by_alias(self, container):
        cmd = BaseCommand(container)
        cmd.COMMAND_NAME = "test"
        cmd.ALIASES = ("t", "测试")
        assert cmd.match("t") is True
        assert cmd.match("测试") is True

    def test_no_match(self, container):
        cmd = BaseCommand(container)
        cmd.COMMAND_NAME = "test"
        assert cmd.match("other") is False

    def test_execute_raises_not_implemented(self, container):
        cmd = BaseCommand(container)
        with pytest.raises(NotImplementedError):
            cmd.execute([])

    def test_has_db_reference(self, container):
        cmd = BaseCommand(container)
        assert cmd.db is container.db


# ─── CommandDispatcher Tests ────────────────────────────────────────────────


class TestCommandDispatcher:
    def test_auto_register_discovers_commands(self, container):
        d = CommandDispatcher(container)
        names = [c.COMMAND_NAME for c in d.all_commands()]
        assert len(names) > 0
        # Key commands must exist
        assert "status" in names
        assert "resource" in names
        assert "set" in names
        assert "help" in names
        assert "goals" in names
        assert "exit" in names

    def test_dispatch_unknown_returns_false(self, dispatcher):
        assert dispatcher.dispatch("nonexistent_command_xyz", []) is False

    def test_dispatch_by_name(self, dispatcher):
        # "lang" command should be registered; dispatch should return True
        assert dispatcher.dispatch("lang", []) is True

    def test_dispatch_by_alias(self, dispatcher):
        # "语言" is an alias for "lang"
        assert dispatcher.dispatch("语言", []) is True

    def test_get_command(self, dispatcher):
        cmd = dispatcher.get_command("lang")
        assert cmd is not None
        assert cmd.COMMAND_NAME == "lang"

    def test_get_command_by_alias(self, dispatcher):
        cmd = dispatcher.get_command("语言")
        assert cmd is not None
        assert cmd.COMMAND_NAME == "lang"

    def test_get_command_unknown_returns_none(self, dispatcher):
        assert dispatcher.get_command("nonexistent") is None


# ─── discover_commands Tests ────────────────────────────────────────────────


class TestDiscoverCommands:
    def test_returns_list_of_classes(self):
        commands = discover_commands()
        assert isinstance(commands, list)
        assert len(commands) > 0
        for cls in commands:
            assert issubclass(cls, BaseCommand)
            assert cls is not BaseCommand

    def test_discovers_all_expected_commands(self):
        commands = discover_commands()
        names = {cls.COMMAND_NAME for cls in commands}
        expected = {"status", "resource", "set", "lang", "exit", "help", "goals", "reset"}
        assert expected.issubset(names), f"Missing commands: {expected - names}"


# ─── StatusCommand Tests ────────────────────────────────────────────────────


class TestStatusCommand:
    def test_execute_no_args(self, dispatcher):
        # Should not raise even with no resources set
        assert dispatcher.dispatch("status", []) is True

    def test_execute_with_resources(self, dispatcher, db):
        from allspark.core.models import Resource, ResourceType
        db.upsert_resource(Resource(
            type=ResourceType.POWER, current_amount=100, unit="Wh",
            daily_consumption=5, daily_intake=0, estimated_remaining_hours=20,
        ))
        assert dispatcher.dispatch("status", []) is True


# ─── ResourceCommand Tests ──────────────────────────────────────────────────


class TestResourceCommand:
    def test_execute(self, dispatcher):
        assert dispatcher.dispatch("resource", []) is True


# ─── SetCommand Tests ───────────────────────────────────────────────────────


class TestSetCommand:
    def test_execute_no_args_shows_usage(self, dispatcher):
        assert dispatcher.dispatch("set", []) is True

    def test_execute_set_power(self, dispatcher, db):
        from allspark.core.models import ResourceType
        assert dispatcher.dispatch("set", ["power", "100", "5"]) is True
        resource = db.get_resource(ResourceType.POWER)
        assert resource is not None
        assert resource.current_amount == 100.0

    def test_execute_set_water_chinese(self, dispatcher, db):
        from allspark.core.models import ResourceType
        assert dispatcher.dispatch("set", ["水", "50", "3"]) is True
        resource = db.get_resource(ResourceType.WATER)
        assert resource is not None
        assert resource.current_amount == 50.0

    def test_execute_invalid_type(self, dispatcher):
        assert dispatcher.dispatch("set", ["invalid_type", "100"]) is True

    def test_execute_invalid_number(self, dispatcher):
        assert dispatcher.dispatch("set", ["power", "abc"]) is True

    @pytest.mark.parametrize("value", ["NaN", "Infinity", "-1"])
    def test_execute_unsafe_number_does_not_write(self, dispatcher, db, value):
        from allspark.core.models import ResourceType

        before = db.get_resource(ResourceType.WATER)
        assert dispatcher.dispatch("set", ["water", value, "2"]) is True
        assert db.get_resource(ResourceType.WATER) == before

    def test_execute_unknown_with_bad_people_count_does_not_write(self, dispatcher, db):
        from allspark.core.models import ResourceType

        before = db.get_resource(ResourceType.WATER)
        assert dispatcher.dispatch("set", ["water", "unknown", "bad_count"]) is True
        assert db.get_resource(ResourceType.WATER) == before

    def test_execute_resource_validation_error_does_not_write(self, dispatcher, db):
        from allspark.core.models import ResourceType

        before = db.get_resource(ResourceType.WATER)
        assert dispatcher.dispatch("set", ["water", "10", "2", "0", "0"]) is True
        assert db.get_resource(ResourceType.WATER) == before

    def test_execute_storage_capacity_people_and_estimate(self, dispatcher, db):
        from allspark.core.models import ResourceType

        assert dispatcher.dispatch(
            "set", ["storage", "80", "2", "1", "4", "100", "estimate"]
        ) is True
        resource = db.get_resource(ResourceType.STORAGE)
        assert resource.current_amount == 80
        assert resource.capacity == 100
        assert resource.capacity_known is True
        assert resource.people_count == 4
        assert resource.source == "estimate"

    def test_execute_sustained_resource_is_not_reported_unknown(self, dispatcher, db):
        from allspark.core.models import ResourceType

        assert dispatcher.dispatch(
            "set", ["water", "10", "2", "2", "1", "observed"]
        ) is True
        resource = db.get_resource(ResourceType.WATER)
        assert resource.estimated_remaining_hours == -1
        assert resource.source == "user_input"


# ─── LangCommand Tests ──────────────────────────────────────────────────────


class TestLangCommand:
    def test_execute_no_args(self, dispatcher):
        assert dispatcher.dispatch("lang", []) is True

    def test_switch_to_en(self, dispatcher):
        assert dispatcher.dispatch("lang", ["en"]) is True
        # Switch back for other tests
        set_language("zh", persist=False)

    def test_switch_to_zh(self, dispatcher):
        assert dispatcher.dispatch("lang", ["zh"]) is True

    def test_unsupported_language(self, dispatcher):
        assert dispatcher.dispatch("lang", ["fr"]) is True


# ─── ExitCommand Tests ──────────────────────────────────────────────────────


class TestExitCommand:
    def test_execute(self, dispatcher):
        # ExitCommand needs cli_instance — get it from dispatcher
        mock_cli = MagicMock()
        cmd = dispatcher.get_command("exit")
        cmd.cli = mock_cli
        cmd.execute([])
        assert mock_cli.running is False


# ─── HelpCommand Tests ──────────────────────────────────────────────────────


class TestHelpCommand:
    def test_execute(self, dispatcher):
        assert dispatcher.dispatch("help", []) is True


# ─── GoalsCommand Tests ─────────────────────────────────────────────────────


class TestGoalsCommand:
    def test_execute_no_args(self, dispatcher):
        assert dispatcher.dispatch("goals", []) is True

    def test_add_goal(self, dispatcher, db):
        assert dispatcher.dispatch("goals", ["add", "Build", "shelter"]) is True
        goals = db.get_active_goals()
        assert len(goals) > 0
        assert goals[0].title == "Build shelter"

    def test_add_goal_chinese(self, dispatcher, db):
        assert dispatcher.dispatch("goals", ["添加", "搭建庇护所"]) is True
        goals = db.get_active_goals()
        assert len(goals) > 0
        assert goals[0].title == "搭建庇护所"

    def test_add_goal_no_title(self, dispatcher):
        assert dispatcher.dispatch("goals", ["add"]) is True

    def test_complete_goal(self, dispatcher, db):
        # Add a goal first
        dispatcher.dispatch("goals", ["add", "Test goal"])
        goals = db.get_active_goals()
        goal_id = goals[0].id
        assert dispatcher.dispatch("goals", ["complete", goal_id]) is True

    def test_complete_goal_missing_id(self, dispatcher):
        assert dispatcher.dispatch("goals", ["complete"]) is True

    def test_complete_nonexistent_goal(self, dispatcher):
        assert dispatcher.dispatch("goals", ["complete", "nonexistent_id"]) is True

    def test_abandon_goal(self, dispatcher, db):
        dispatcher.dispatch("goals", ["add", "Test abandon"])
        goals = db.get_active_goals()
        goal_id = goals[0].id
        assert dispatcher.dispatch("goals", ["abandon", goal_id]) is True

    def test_pause_and_resume_goal(self, dispatcher, db):
        dispatcher.dispatch("goals", ["add", "Test pause"])
        goals = db.get_active_goals()
        goal_id = goals[0].id
        assert dispatcher.dispatch("goals", ["pause", goal_id]) is True
        assert dispatcher.dispatch("goals", ["resume", goal_id]) is True

    def test_auto_generate(self, dispatcher):
        assert dispatcher.dispatch("goals", ["auto"]) is True

    def test_unknown_subcommand(self, dispatcher):
        assert dispatcher.dispatch("goals", ["unknown_sub"]) is True


# ─── ResetCommand Tests ─────────────────────────────────────────────────────


class TestResetCommand:
    def test_execute_no_args_shows_usage(self, dispatcher):
        assert dispatcher.dispatch("reset", []) is True

    def test_status_subcommand(self, dispatcher):
        assert dispatcher.dispatch("reset", ["status"]) is True

    def test_unknown_subcommand(self, dispatcher):
        assert dispatcher.dispatch("reset", ["unknown"]) is True


# ─── CommunityCommand Tests ────────────────────────────────────────────────


class TestCommunityCommand:
    def test_execute_no_args(self, dispatcher):
        assert dispatcher.dispatch("community", []) is True

    def test_status_subcommand(self, dispatcher):
        assert dispatcher.dispatch("community", ["status"]) is True


# ─── PowerCommand Tests ──────────────────────────────────────────────────


class TestPowerCommand:
    def test_execute_no_args(self, dispatcher):
        assert dispatcher.dispatch("power", []) is True
