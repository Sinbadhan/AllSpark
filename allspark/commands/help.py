
from allspark.commands.base import BaseCommand


class HelpCommand(BaseCommand):
    COMMAND_NAME = "help"
    ALIASES = ("帮助", "h", "?")

    def execute(self, args: list[str]) -> None:
        engine = self.container.get("rule_engine")
        if engine:
            self.console.print(engine._handle_help())
