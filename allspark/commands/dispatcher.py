import importlib
import inspect
import logging
from pathlib import Path

from allspark.commands.base import BaseCommand
from allspark.container import ServiceContainer

logger = logging.getLogger(__name__)


def discover_commands() -> list[type[BaseCommand]]:
    """Scan the commands package for BaseCommand subclasses."""
    commands_dir = Path(__file__).resolve().parent
    command_classes: list[type[BaseCommand]] = []

    for py_file in sorted(commands_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        module_name = f"allspark.commands.{py_file.stem}"
        try:
            mod = importlib.import_module(module_name)
        except Exception as e:
            logger.warning("Failed to import %s: %s", module_name, e)
            continue
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if issubclass(obj, BaseCommand) and obj is not BaseCommand:
                command_classes.append(obj)

    return command_classes


class CommandDispatcher:
    def __init__(self, container: ServiceContainer, *, auto_register: bool = True, **extra_kwargs):
        self.container = container
        self._commands: dict[str, BaseCommand] = {}
        self._alias_map: dict[str, str] = {}
        if auto_register:
            self.auto_register_all(**extra_kwargs)

    def auto_register_all(self, **extra_kwargs) -> None:
        """Discover and register all BaseCommand subclasses."""
        for cls in discover_commands():
            try:
                sig = inspect.signature(cls.__init__)
                kwargs = {}
                for param_name in extra_kwargs:
                    if param_name in sig.parameters:
                        kwargs[param_name] = extra_kwargs[param_name]
                instance = cls(self.container, **kwargs)
                self.register(instance)
            except Exception as e:
                logger.warning("Failed to register command %s: %s", cls, e)

    def register(self, command: BaseCommand) -> None:
        name = command.COMMAND_NAME
        self._commands[name] = command
        self._alias_map[name] = name
        for alias in command.ALIASES:
            self._alias_map[alias] = name

    def dispatch(self, cmd: str, args: list[str]) -> bool:
        resolved = self._alias_map.get(cmd)
        if resolved is None:
            return False
        command = self._commands.get(resolved)
        if command is None:
            return False
        command.execute(args)
        return True

    def get_command(self, name: str) -> BaseCommand | None:
        resolved = self._alias_map.get(name)
        if resolved is None:
            return None
        return self._commands.get(resolved)

    def all_commands(self) -> list[BaseCommand]:
        return list(self._commands.values())
