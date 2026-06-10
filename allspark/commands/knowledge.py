from rich.panel import Panel
from rich.table import Table

from allspark.commands.base import BaseCommand
from allspark.core.i18n import t


class MapCommand(BaseCommand):
    COMMAND_NAME = "map"
    ALIASES = ()

    def execute(self, args: list[str]) -> None:
        maps = self.container.get("map_system")

        if not args:
            self.console.print(maps.format_map())
            return

        subcmd = args[0].lower()

        if subcmd == "add":
            self.console.print(f"[bold]{t('add_to_map')}[/]")
            name = self.console.input(t("map_name_prompt")).strip()
            if not name:
                self.console.print(f"[dim]{t('map_add_cancelled')}[/]")
                return
            poi_type = self.console.input(t("map_type_prompt")).strip() or "other"
            desc = self.console.input(t("map_desc_prompt")).strip()
            dist_str = self.console.input(t("map_dist_prompt")).strip()
            dist = float(dist_str) if dist_str else 0.0
            direction = self.console.input(t("map_dir_prompt")).strip()
            notes = self.console.input(t("map_notes_prompt")).strip()

            poi = maps.add_poi(
                name=name, poi_type=poi_type, description=desc,
                distance_km=dist, direction=direction, notes=notes
            )
            self.console.print(f"[green]{t('map_added', name=poi.name, id=poi.id)}[/]")

        elif subcmd == "remove" and len(args) > 1:
            maps.remove_poi(args[1])
            self.console.print(f"[green]{t('map_deleted', id=args[1])}[/]")

        elif subcmd in ("water", "shelter", "food", "danger", "resource", "camp", "medical"):
            pois = maps.get_by_type(subcmd)
            if pois:
                for p in pois:
                    self.console.print(maps.format_poi_detail(p))
                    self.console.print("")
            else:
                self.console.print(f"[dim]{t('map_no_type_locations', type=subcmd)}[/]")

        else:
            self.console.print(f"[dim]{t('map_usage_msg')}[/]")


class TaskCommand(BaseCommand):
    COMMAND_NAME = "task"
    ALIASES = ("任务", "tasks")

    def execute(self, args: list[str]) -> None:
        planner = self.container.require("mission_planner")
        survival = self.container.require("survival_engine")

        if not args:
            tasks = planner.get_all_active()
            if not tasks:
                assessment = survival.assess()
                tasks = planner.suggest_tasks(assessment["resources"])
            self.console.print(planner.format_tasks(tasks))
            return

        subcmd = args[0].lower()
        if subcmd in ("完成", "done", "complete") and len(args) > 1:
            planner.complete_task(args[1])
            self.console.print(f"[green]{t('task_done_msg', id=args[1])}[/]")
        elif subcmd in ("开始", "start") and len(args) > 1:
            planner.start_task(args[1])
            self.console.print(f"[green]{t('task_start_msg', id=args[1])}[/]")
        elif subcmd in ("失败", "fail") and len(args) > 1:
            planner.fail_task(args[1])
            self.console.print(f"[yellow]{t('task_fail_msg', id=args[1])}[/]")
        else:
            self.console.print(f"[dim]{t('task_usage_msg')}[/]")


class KnowledgeCommand(BaseCommand):
    COMMAND_NAME = "know"
    ALIASES = ("知识", "knowledge")

    def execute(self, args: list[str]) -> None:
        knowledge = self.container.get("knowledge")

        if not knowledge:
            self.console.print(f"[yellow]{t('knowledge_module_not_loaded')}[/]")
            return

        if not args:
            categories = knowledge.get_categories()
            self.console.print(f"[bold]{t('knowledge_categories')}[/]")
            for cat in categories:
                subcats = knowledge.get_subcategories(cat)
                self.console.print(f"  {cat}: {', '.join(subcats)}")
            self.console.print(f"\n[dim]{t('knowledge_usage')}[/]")
            return

        entries = knowledge.search_by_language(" ".join(args), limit=10)
        if not entries and len(args) >= 2:
            entries = knowledge.get_by_category(args[0], args[1])

        if not entries:
            self.console.print(f"[dim]{t('no_knowledge', topic=' '.join(args))}[/]")
            return

        for entry in entries:
            self.console.print(Panel(
                knowledge.format_entry(entry),
                title=f"Tier {entry.priority} | {entry.category}/{entry.subcategory}",
                border_style="green" if entry.priority == 0 else "yellow" if entry.priority == 1 else "blue"
            ))


class ExperienceCommand(BaseCommand):
    COMMAND_NAME = "exp"
    ALIASES = ("经验", "experience")

    def execute(self, args: list[str]) -> None:
        exp = self.container.get("experience")

        if not args:
            stats = exp.get_stats()
            table = Table(title=t("title_experience"))
            table.add_column(t("field_metric"), style="cyan")
            table.add_column(t("field_value"))
            table.add_row(t("field_total_experiences"), str(stats["total_experiences"]))
            table.add_row(t("field_patterns_detected"), str(stats["patterns_detected"]))
            table.add_row(t("field_knowledge_promoted"), str(stats["knowledge_promoted"]))
            self.console.print(table)

            patterns = exp.get_patterns()
            if patterns:
                ptable = Table(title=t("title_patterns"))
                ptable.add_column(t("field_event"))
                ptable.add_column(t("field_count"), justify="right")
                ptable.add_column(t("field_promoted"))
                for p in patterns[:10]:
                    ptable.add_row(
                        p["event"],
                        str(p["count"]),
                        "✅" if p["promoted"] else "—",
                    )
                self.console.print(ptable)

            self.console.print(f"\n[dim]{t('exp_usage')}[/]")
            return

        subcmd = args[0].lower()

        if subcmd in ("log", "记录") and len(args) >= 3:
            event = args[1]
            outcome = " ".join(args[2:])
            lesson = ""
            if "|" in outcome:
                parts = outcome.split("|", 1)
                outcome = parts[0].strip()
                lesson = parts[1].strip()
            entry = exp.log(event=event, outcome=outcome, lesson=lesson)
            self.console.print(f"[green]✓ {t('exp_logged')}: {entry.id}[/]")
            return

        if subcmd in ("patterns", "模式"):
            patterns = exp.get_patterns()
            if not patterns:
                self.console.print(f"[dim]{t('exp_no_patterns')}[/]")
                return
            ptable = Table(title=t("title_patterns"))
            ptable.add_column(t("field_event"))
            ptable.add_column(t("field_count"), justify="right")
            ptable.add_column(t("field_promoted"))
            for p in patterns:
                ptable.add_row(
                    p["event"],
                    str(p["count"]),
                    f"✅ → {p['knowledge_id']}" if p["promoted"] else "—",
                )
            self.console.print(ptable)
            return

        if subcmd in ("recent", "最近"):
            entries = exp.get_recent(10)
            if not entries:
                self.console.print(f"[dim]{t('exp_no_entries')}[/]")
                return
            for e in entries:
                status = "✅" if e.related_knowledge_id else "  "
                self.console.print(f"  {status} [{e.id}] {e.event} → {e.outcome}")
            return

        self.console.print(f"[dim]{t('exp_usage')}[/]")
