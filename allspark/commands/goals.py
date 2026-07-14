from rich.table import Table

from allspark.commands.base import BaseCommand
from allspark.core.i18n import render, t


class GoalCommand(BaseCommand):
    COMMAND_NAME = "goals"
    ALIASES = ("目标", "goal")

    def execute(self, args: list[str]) -> None:
        goal_engine = self.container.get("goal_engine")
        if not goal_engine:
            self.console.print(f"[yellow]{t('goal_not_loaded')}[/]")
            return

        ge = goal_engine

        if not args:
            summary = ge.get_goal_summary()
            self.console.print(summary)
            return

        sub = args[0].lower()

        if sub in ("添加", "add", "新建", "new"):
            title = " ".join(args[1:]) if len(args) > 1 else ""
            if not title:
                self.console.print(f"[yellow]{t('goal_specify_title')}[/]")
                return
            goal = ge.add_manual_goal(title=title)
            self.console.print(t("goal_added", title=render(goal.title)))
            if goal.milestone_count > 0:
                milestones = self.db.get_milestones_by_goal(goal.id)
                for ms in milestones:
                    status_icon = "✅" if ms.done else "⬜"
                    self.console.print(f"  {status_icon} {ms.order}. {render(ms.description)}")

        elif sub in ("完成", "complete", "done"):
            goal_id = args[1] if len(args) > 1 else ""
            if not goal_id:
                self.console.print(f"[yellow]{t('goal_specify_id')}[/]")
                return
            result = ge.complete_goal(goal_id)
            if result:
                goal = self.db.get_goal(goal_id)
                self.console.print(t("goal_completed", title=render(goal.title) if goal else goal_id))
            else:
                self.console.print(t("goal_not_found", id=goal_id))

        elif sub in ("放弃", "abandon", "取消"):
            goal_id = args[1] if len(args) > 1 else ""
            if not goal_id:
                self.console.print(f"[yellow]{t('goal_specify_id')}[/]")
                return
            result = ge.abandon_goal(goal_id)
            if result:
                goal = self.db.get_goal(goal_id)
                self.console.print(t("goal_abandoned", title=render(goal.title) if goal else goal_id))
            else:
                goal = self.db.get_goal(goal_id)
                if goal and goal.priority == "critical":
                    self.console.print(t("goal_cannot_abandon_critical"))
                else:
                    self.console.print(t("goal_not_found", id=goal_id))

        elif sub in ("暂停", "pause"):
            goal_id = args[1] if len(args) > 1 else ""
            if not goal_id:
                self.console.print(f"[yellow]{t('goal_specify_id')}[/]")
                return
            result = ge.pause_goal(goal_id)
            if result:
                goal = self.db.get_goal(goal_id)
                self.console.print(t("goal_paused", title=render(goal.title) if goal else goal_id))
            else:
                goal = self.db.get_goal(goal_id)
                if goal and goal.priority == "critical":
                    self.console.print(t("goal_cannot_pause_critical"))
                else:
                    self.console.print(t("goal_not_found", id=goal_id))

        elif sub in ("恢复", "resume"):
            goal_id = args[1] if len(args) > 1 else ""
            if not goal_id:
                self.console.print(f"[yellow]{t('goal_specify_id')}[/]")
                return
            result = ge.resume_goal(goal_id)
            if result:
                goal = self.db.get_goal(goal_id)
                self.console.print(t("goal_resumed", title=render(goal.title) if goal else goal_id))
            else:
                self.console.print(t("goal_not_found", id=goal_id))

        elif sub in ("里程碑", "milestones", "ms"):
            goal_id = args[1] if len(args) > 1 else ""
            if not goal_id:
                self.console.print(f"[yellow]{t('goal_specify_id')}[/]")
                return
            detail = ge.get_goal_detail(goal_id)
            if not detail:
                self.console.print(t("goal_not_found", id=goal_id))
                return
            goal = detail["goal"]
            self.console.print(f"[bold]{render(goal.title)}[/] — {render(goal.description)}")
            for ms in detail["milestones"]:
                status_icon = "✅" if ms.done else "⬜"
                self.console.print(f"  {status_icon} {ms.order}. {render(ms.description)}")
            progress_pct = int(goal.progress * 100)
            self.console.print(f"\n  {t('goal_progress', pct=progress_pct, done=goal.milestone_done, total=goal.milestone_count)}")

        elif sub in ("自动生成", "auto", "generate"):
            generated = ge.auto_generate_goals()
            if generated:
                self.console.print(f"[green]{t('goal_generated', count=len(generated))}[/]")
                for g in generated:
                    title_str = render(g.title)
                    self.console.print(f"  🔴 {title_str}" if g.priority == "critical" else f"  🟡 {title_str}")
            else:
                self.console.print(f"[dim]{t('goal_no_new')}[/]")

        else:
            self.console.print(t("goal_usage"))


class ResetCommand(BaseCommand):
    COMMAND_NAME = "reset"
    ALIASES = ("重置",)

    def __init__(self, container, cli_instance=None):
        super().__init__(container)
        self.cli = cli_instance

    def execute(self, args: list[str]) -> None:
        reset_manager = self.container.get("reset_manager")
        if not reset_manager:
            self.console.print(f"[yellow]{t('reset_not_loaded')}[/]")
            return

        rm = reset_manager

        if not args:
            self.console.print(t("reset_usage"))
            return

        sub = args[0].lower()

        if sub in ("状态", "status"):
            status = rm.get_reset_status()
            table = Table(title=t("title_reset_status"))
            table.add_column(t("field_item"), style="cyan")
            table.add_column(t("field_value"))
            table.add_row(t("field_last_reset"), str(status.get("last_reset", t("field_never"))))
            table.add_row(t("field_cooldown"), f"{status['cooldown_hours']}h")
            table.add_row(t("field_can_reset"), f"✅ {t('field_yes')}" if status["can_reset"] else f"❌ {t('field_no_cooldown')}")
            self.console.print(table)

        elif sub in ("评估", "assessment", "l1"):
            from allspark.core.models import ResetLevel
            evaluation = rm.evaluate_reset(ResetLevel.ASSESSMENT)
            self._print_reset_evaluation(evaluation)
            if evaluation["allowed"]:
                confirm = self.console.input(f"[bold red]{t('reset_confirm_l1')}[/]").strip().lower()
                if confirm in ("yes", "是", "y"):
                    result = rm.execute_reset(
                        ResetLevel.ASSESSMENT, performed_by="cli"
                    )
                    if result["status"] == "ok":
                        self.console.print(t("reset_executed", level="L1"))
                    else:
                        self.console.print(t("reset_rejected", reason=result.get("reason", "")))

        elif sub in ("档案", "archive", "l2"):
            from allspark.core.models import ResetLevel
            evaluation = rm.evaluate_reset(ResetLevel.ARCHIVE)
            self._print_reset_evaluation(evaluation)
            if evaluation["allowed"]:
                confirm = self.console.input(f"[bold red]{t('reset_confirm_l2')}[/]").strip().lower()
                if confirm in ("yes", "是", "y"):
                    result = rm.execute_reset(
                        ResetLevel.ARCHIVE, performed_by="cli"
                    )
                    if result["status"] == "ok":
                        self.console.print(t("reset_executed", level="L2"))
                    else:
                        self.console.print(t("reset_rejected", reason=result.get("reason", "")))

        elif sub in ("出厂", "factory", "l3"):
            from allspark.core.models import ResetLevel
            evaluation = rm.evaluate_reset(ResetLevel.FACTORY)
            self._print_reset_evaluation(evaluation)
            if evaluation["allowed"]:
                confirm = self.console.input(f"[bold red]{t('reset_confirm_l3')}[/]").strip()
                if confirm == "FACTORY":
                    result = rm.execute_reset(
                        ResetLevel.FACTORY, force=True, performed_by="cli"
                    )
                    if result["status"] == "ok":
                        self.console.print(t("reset_executed", level="L3"))
                        self.console.print(f"[bold yellow]{t('reset_system_restart')}[/]")
                        self.console.print(f"[dim]{t('reset_all_erased')}[/]")
                        if self.cli:
                            self.cli.running = False
                    else:
                        self.console.print(t("reset_rejected", reason=result.get("reason", "")))
                else:
                    self.console.print(f"[dim]{t('reset_factory_cancelled')}[/]")

        else:
            self.console.print(t("reset_usage"))

    def _print_reset_evaluation(self, evaluation: dict):
        level_name = evaluation.get("level_name", "")
        allowed = evaluation.get("allowed", False)
        description = evaluation.get("description", "")

        self.console.print(f"\n[bold]{t('reset_evaluation_title', level=level_name)}[/]")
        self.console.print(f"  {t('reset_allowed', status='✅' if allowed else '❌')}")
        if description:
            self.console.print(f"  {t('reset_description', desc=description)}")
        if evaluation.get("affected_data"):
            self.console.print(f"  {t('reset_affected_data')}")
            for item in evaluation["affected_data"]:
                self.console.print(f"    - {item}")
        if evaluation.get("warnings"):
            for w in evaluation["warnings"]:
                self.console.print(f"  [yellow]{t('reset_warning', msg=w)}[/]")
        if evaluation.get("backup_recommended"):
            self.console.print(f"  [dim]{t('reset_backup_hint')}[/]")
