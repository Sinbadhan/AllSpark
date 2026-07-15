import sys

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from allspark import __version__
from allspark.adapters.init_wizard import run_init_wizard
from allspark.bootstrap import (
    cleanup_application_candidate,
    prepare_application,
    rollback_initialization_draft,
)
from allspark.commands.dispatcher import CommandDispatcher
from allspark.container import ServiceContainer
from allspark.core.database import Database
from allspark.core.i18n import get_language, init_language, mark, render, set_language, t
from allspark.core.models import OperatingMode
from allspark.services.rule_engine import RuleEngine

console = Console()


class SparkCLI:
    def __init__(self, db_path=None):
        self.db = Database(db_path)
        init_language(self.db)
        self._container: ServiceContainer | None = None
        self._engine: RuleEngine | None = None
        self.running = True
        self.init_result = None
        self._flags = None
        self._dispatcher: CommandDispatcher | None = None

    @property
    def container(self) -> ServiceContainer:
        if self._container is None:
            raise RuntimeError("CLI container accessed before bootstrap")
        return self._container

    @container.setter
    def container(self, value: ServiceContainer) -> None:
        self._container = value

    @property
    def engine(self) -> RuleEngine:
        if self._engine is None:
            raise RuntimeError("CLI engine accessed before bootstrap")
        return self._engine

    @engine.setter
    def engine(self, value: RuleEngine) -> None:
        self._engine = value

    @property
    def dispatcher(self) -> CommandDispatcher:
        if self._dispatcher is None:
            raise RuntimeError("CLI dispatcher accessed before setup")
        return self._dispatcher

    def run(self):
        needs_initialization = not self.db.is_initialized()
        previous_language = get_language()
        prepared = None
        try:
            if needs_initialization:
                self.init_result = run_init_wizard(self.db)
                if self.init_result and "hardware" in self.init_result:
                    self._flags = self.init_result["hardware"].get("flags")

            prepared = prepare_application(self.db, flags=self._flags)
            if needs_initialization:
                if self.init_result is None:
                    raise RuntimeError("Initialization wizard returned no result")
                language = self.init_result.get("language", previous_language)
                assessment = self.init_result.get("assessment")
                if assessment is None:
                    raise RuntimeError("Initialization wizard returned no assessment")
                survivor = self.init_result.get("survivor", {})
                self.db.save_survivor_state(
                    "name", survivor.get("name") or t("init_default_name")
                )
                self.db.save_survivor_state(
                    "gps_input", survivor.get("gps_input", "")
                )
                self.db.save_survivor_state(
                    "skills", ",".join(survivor.get("skills", []))
                )
                prepared.container.require("initial_assessment").apply(assessment)
                plan_service = prepared.container.require("survival_plan")
                plan = plan_service.generate(assessment)
                plan_id = self.init_result.get("plan_id")
                primary_action_id = self.init_result.get("primary_action_id")
                if not isinstance(plan_id, str) or not isinstance(
                    primary_action_id, str
                ):
                    raise RuntimeError("Initialization wizard returned no plan selection")
                plan_service.persist_draft(
                    plan,
                    plan_id=plan_id,
                    accepted_action_id=primary_action_id,
                )
                self.db.finalize_initialization(
                    language, plan.id, primary_action_id
                )

            self._container = prepared.container
            self._engine = prepared.engine
        except Exception:
            rollback_initialization_draft(self.db)
            if prepared is not None:
                cleanup_application_candidate(prepared.bootstrap)
            if needs_initialization:
                set_language(previous_language, persist=False)
            raise

        if needs_initialization:
            console.print(f"\n[bold green]{t('init_complete_msg')}[/]")
            console.print(f"[dim]{t('init_complete_hint')}[/]\n")
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
        self._dispatcher = CommandDispatcher(self.container, cli_instance=self)

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
        has_data = any(r.amount_known for r in resources)
        if not has_data:
            console.print(f"\n[dim]{t('resource_offline_hint')}[/]")

        console.print(f"\n[dim]{t('help_help')}[/]")

        self._phase7_post_init()

    def _phase7_post_init(self):
        timeline = self.container.get("timeline")
        if timeline:
            timeline.add_event(
                event_type="system_event",
                title=mark("spark_activated"),
                description=mark("spark_activated_desc"),
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
                        console.print(f"  {icon} [{g.category}] {render(g.title)}")
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

        if self.dispatcher.dispatch(cmd, args):
            return

        response = self.engine.process_input(user_input, conversation_id="cli")
        console.print(response)


def main():
    db_path = None
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    cli = SparkCLI(db_path)
    cli.run()


if __name__ == "__main__":
    main()
