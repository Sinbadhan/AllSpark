
from allspark.commands.base import BaseCommand
from allspark.i18n import t



class HelpCommand(BaseCommand):
    COMMAND_NAME = "help"
    ALIASES = ("帮助", "h", "?")

    def execute(self, args: list[str]) -> None:
        from allspark.rule_engine import RuleEngine
        engine = RuleEngine(self.container)
        self.console.print(engine._handle_help())
