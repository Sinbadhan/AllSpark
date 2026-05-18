from allspark.container import ServiceContainer
from allspark.commands.base import BaseCommand


class CommandDispatcher:
    def __init__(self, container: ServiceContainer):
        self.container = container
        self._commands: dict[str, BaseCommand] = {}
        self._alias_map: dict[str, str] = {}

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
