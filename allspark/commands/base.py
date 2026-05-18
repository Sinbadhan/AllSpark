from rich.console import Console

from allspark.container import ServiceContainer
from allspark.database import Database
from allspark.i18n import get_language


class BaseCommand:
    COMMAND_NAME: str = ""
    ALIASES: tuple[str, ...] = ()

    def __init__(self, container: ServiceContainer, **kwargs):
        self.container = container
        self.db: Database = container.db
        self.console = Console()

    @property
    def lang(self) -> str:
        return get_language()

    def match(self, cmd: str) -> bool:
        if cmd == self.COMMAND_NAME:
            return True
        return cmd in self.ALIASES

    def execute(self, args: list[str]) -> None:
        raise NotImplementedError
