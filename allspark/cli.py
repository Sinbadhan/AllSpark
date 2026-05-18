import sys
import shlex

from rich.console import Console
from rich.panel import Panel
from allspark import __version__
from rich.table import Table
from rich.text import Text

from allspark.database import Database
from allspark.container import ServiceContainer
from allspark.rule_engine import RuleEngine
from allspark.bootstrap import ApplicationBootstrap
from allspark.commands.dispatcher import CommandDispatcher
from allspark.commands.basic import StatusCommand, ResourceCommand, LangCommand, SetCommand, ExitCommand
from allspark.commands.knowledge import MapCommand, TaskCommand, KnowledgeCommand, ExperienceCommand
from allspark.commands.ai import LLMCommand, ModuleCommand, SKFCommand, VerifyCommand
from allspark.commands.governance import GovernanceCommand, TradeCommand
from allspark.commands.comms import NetworkCommand, VisionCommand
from allspark.commands.hardware import PowerCommand, SensorCommand, PreserveCommand
from allspark.commands.goals import GoalCommand, ResetCommand
from allspark.commands.survival import (
    BriefingCommand, TimelineCommand, DiaryCommand,
    WeatherCommand, PsychologyCommand, GPSCommand,
    EnvironmentCommand, VoiceCommand,
)
from allspark.commands.help import HelpCommand
from allspark.commands.docker import DockerCommand
from allspark.models import ResourceType, OperatingMode
from allspark.i18n import t, set_language, get_language, detect_language, init_language
from allspark.init_wizard import run_init_wizard
from allspark.hardware import FeatureFlags


console = Console()


class SparkCLI:
    def __init__(self, db_path=None):
        self.db = Database(db_path)
        init_language(self.db)
        self.container = None
        self.engine = None
        self.running = True
        self.init_result = None
        self._flags = None
        self._dispatcher = None

    def run(self):
        if not self.db.is_initialized():
            self.init_result = run_init_wizard(self.db)
            if self.init_result and "hardware" in self.init_result:
                self._flags = self.init_result["hardware"].get("flags")

        self.container = ApplicationBootstrap(self.db, flags=self._flags).bootstrap()
        self.engine = RuleEngine(self.container)
        self._setup_dispatcher()
        self._print_banner()
        self._print_initial_status()

        while self.running:
            try:
                prompt = t("input_prompt")
                user_input = console.input(f"\n[bold cyan]{prompt}[/] ").strip()
                if not user_input:
                    continue
                self._process_command(user_input)
            except KeyboardInterrupt:
                console.print(f"\n\n{t('exit_message')}")
                self.running = False
            except EOFError:
                self.running = False

    def _setup_dispatcher(self):
        self._dispatcher = CommandDispatcher(self.container)
        self._dispatcher.register(StatusCommand(self.container))
        self._dispatcher.register(ResourceCommand(self.container))
        self._dispatcher.register(LangCommand(self.container))
        self._dispatcher.register(SetCommand(self.container))
        self._dispatcher.register(ExitCommand(self.container, cli_instance=self))
        self._dispatcher.register(MapCommand(self.container))
        self._dispatcher.register(TaskCommand(self.container))
        self._dispatcher.register(KnowledgeCommand(self.container))
        self._dispatcher.register(ExperienceCommand(self.container))
        self._dispatcher.register(LLMCommand(self.container))
        self._dispatcher.register(ModuleCommand(self.container))
        self._dispatcher.register(SKFCommand(self.container))
        self._dispatcher.register(VerifyCommand(self.container))
        self._dispatcher.register(GovernanceCommand(self.container))
        self._dispatcher.register(TradeCommand(self.container))
        self._dispatcher.register(NetworkCommand(self.container))
        self._dispatcher.register(VisionCommand(self.container))
        self._dispatcher.register(PowerCommand(self.container))
        self._dispatcher.register(SensorCommand(self.container))
        self._dispatcher.register(PreserveCommand(self.container))
        self._dispatcher.register(GoalCommand(self.container))
        self._dispatcher.register(ResetCommand(self.container, cli_instance=self))
        self._dispatcher.register(BriefingCommand(self.container))
        self._dispatcher.register(TimelineCommand(self.container))
        self._dispatcher.register(DiaryCommand(self.container))
        self._dispatcher.register(WeatherCommand(self.container))
        self._dispatcher.register(PsychologyCommand(self.container))
        self._dispatcher.register(GPSCommand(self.container))
        self._dispatcher.register(EnvironmentCommand(self.container))
        self._dispatcher.register(VoiceCommand(self.container))
        self._dispatcher.register(HelpCommand(self.container))
        self._dispatcher.register(DockerCommand(self.container))

    def _print_banner(self):
        banner = Text()
        banner.append(f"ALLSPARK v{__version__}\n", style="bold red")
        banner.append(t("app_subtitle") + "\n", style="dim")
        banner.append("━━━━━━━━━━━━━━━━━━━━━━━━━━", style="dim")
        banner.append(f"\n{t('app_mission')}", style="italic")
        console.print(Panel(banner, border_style="red", padding=(1, 2)))

    def _print_initial_status(self):
        resource_mgr = self.container.require("resource_manager")
        personality = self.container.require("personality")
        survival = self.container.require("survival_engine")

        warnings = resource_mgr.check_warnings()
        mode, changed = resource_mgr.update_operating_mode()
        mode_names = {
            OperatingMode.PROACTIVE: t("mode_proactive"),
            OperatingMode.STANDARD: t("mode_standard"),
            OperatingMode.ECONOMY: t("mode_economy"),
            OperatingMode.HIBERNATION: t("mode_hibernation"),
            OperatingMode.RECOVERY: t("mode_recovery"),
        }
        personality.determine_mode(
            mode, warnings,
            survival.assess()["phase"]
        )
        greeting = personality.greet()
        console.print(f"\n{greeting}")

        mode_emoji = {
            OperatingMode.PROACTIVE: "🟢",
            OperatingMode.STANDARD: "🟡",
            OperatingMode.ECONOMY: "🟠",
            OperatingMode.HIBERNATION: "🔴",
            OperatingMode.RECOVERY: "🔵",
        }
        emoji = mode_emoji.get(mode, "⚪")
        mode_label = mode_names.get(mode, mode.value)
        console.print(t("operating_mode_fmt", emoji=emoji, mode=mode_label))

        if warnings:
            console.print("")
            for w in warnings:
                style = "bold red" if w["level"] == "critical" else "yellow"
                icon = "🚨" if w["level"] == "critical" else "⚠️"
                console.print(f"  {icon} [{style}]{w['message']}[/]")

        resources = resource_mgr.get_all_resources()
        has_data = any(r.current_amount > 0 for r in resources)
        if not has_data:
            console.print(f"\n[dim]{t('resource_offline_hint')}[/]")

        console.print(f"\n[dim]{t('help_help')}[/]")

        self._phase7_post_init()

    def _phase7_post_init(self):
        timeline = self.container.get("timeline")
        if timeline:
            timeline.add_event(
                event_type="system_event",
                title=t("spark_activated"),
                description=t("spark_activated_desc"),
            )

        goal_engine = self.container.get("goal_engine")
        if goal_engine:
            active_goals = goal_engine.get_active_goals()
            if not active_goals:
                console.print(f"\n[bold blue]{t('goals_auto_generating')}[/]")
                goals = goal_engine.auto_generate_goals()
                if goals:
                    console.print(f"[green]{t('goals_auto_generated', count=len(goals))}[/]")
                    for g in goals[:3]:
                        icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(g.priority, "⚪")
                        console.print(f"  {icon} [{g.category}] {g.title}")
                    if len(goals) > 3:
                        console.print(f"  {t('goals_and_more', count=len(goals) - 3)}")
                else:
                    console.print(f"[dim]{t('goals_no_urgent')}[/]")

        daily_briefing = self.container.get("daily_briefing")
        if daily_briefing:
            console.print(f"\n[bold cyan]{t('briefing_generating')}[/]")
            briefing = daily_briefing.generate()
            console.print(briefing)

    def _process_command(self, user_input: str):
        parts = user_input.split()
        if not parts:
            return
        cmd = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        if self._dispatcher.dispatch(cmd, args):
            return

        response = self.engine.process_input(user_input)
        console.print(response)


def main():
    db_path = None
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    cli = SparkCLI(db_path)
    cli.run()


if __name__ == "__main__":
    main()
