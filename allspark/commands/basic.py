from rich.table import Table
from rich.panel import Panel

from allspark.commands.base import BaseCommand
from allspark.container import ServiceContainer
from allspark.models import ResourceType, OperatingMode
from allspark.i18n import t



class StatusCommand(BaseCommand):
    COMMAND_NAME = "status"
    ALIASES = ("状态",)

    def execute(self, args: list[str]) -> None:
        resource_mgr = self.container.require("resource_manager")
        survival = self.container.require("survival_engine")
        planner = self.container.require("mission_planner")

        assessment = survival.assess()
        mode, _ = resource_mgr.update_operating_mode()
        warnings = resource_mgr.check_warnings()

        mode_names = {
            OperatingMode.PROACTIVE: f"{t('mode_proactive')} 🟢",
            OperatingMode.STANDARD: f"{t('mode_standard')} 🟡",
            OperatingMode.ECONOMY: f"{t('mode_economy')} 🟠",
            OperatingMode.HIBERNATION: f"{t('mode_hibernation')} 🔴",
            OperatingMode.RECOVERY: f"{t('mode_recovery')} 🔵",
        }

        phase_desc = assessment["phase_description"]

        status_table = Table(title=t("assessment_title"), show_header=True, header_style="bold")
        status_table.add_column(t("field_item"), style="cyan")
        status_table.add_column(t("field_status"), style="white")
        status_table.add_row(t("field_mode"), mode_names.get(mode, str(mode)))
        status_table.add_row(t("field_phase"), phase_desc)

        if assessment["bottleneck"]:
            b = assessment["bottleneck"]
            status_table.add_row(
                t("bottleneck_label"),
                f"{b['resource']}({b['remaining']:.1f}{b['unit']})",
                style="bold red"
            )

        self.console.print(status_table)

        if warnings:
            self.console.print(f"\n[bold]{t('warnings_label')}[/]")
            for w in warnings:
                style = "bold red" if w["level"] == "critical" else "yellow"
                self.console.print(f"  [{style}]{w['message']}[/]")

        resources = resource_mgr.get_all_resources()
        res_table = Table(title=t("resource_title"), show_header=True, header_style="bold")
        res_table.add_column(t("field_item"), style="cyan")
        res_table.add_column(t("field_value"), justify="right")
        res_table.add_column(t("field_estimated"), justify="right")
        res_table.add_column(t("field_status"), justify="center")

        for r in resources:
            is_offline = r.current_amount == 0 and r.daily_consumption == 0

            if r.type == ResourceType.POWER:
                name = t("res_power_table")
                if is_offline:
                    res_table.add_row(name, f"[dim]{t('resource_offline')}[/]", "--", "◇")
                    continue
                avail = t("res_unit_hours", hours=r.estimated_remaining_hours)
                status = "🟢" if r.estimated_remaining_hours > 72 else "🟡" if r.estimated_remaining_hours > 24 else "🔴"
                res_table.add_row(name, f"{r.current_amount:.0f}Wh", avail, status)
            elif r.type == ResourceType.WATER:
                name = t("res_water_table")
                if is_offline:
                    res_table.add_row(name, f"[dim]{t('resource_offline')}[/]", "--", "◇")
                    continue
                days = r.estimated_remaining_hours / 24.0
                status = "🟢" if days > 7 else "🟡" if days > 3 else "🔴"
                res_table.add_row(name, f"{r.current_amount:.1f}L", t("res_unit_days", days=days), status)
            elif r.type == ResourceType.FOOD:
                name = t("res_food_table")
                if is_offline:
                    res_table.add_row(name, f"[dim]{t('resource_offline')}[/]", "--", "◇")
                    continue
                days = r.estimated_remaining_hours / 24.0
                status = "🟢" if days > 14 else "🟡" if days > 5 else "🔴"
                res_table.add_row(name, f"{r.current_amount:.0f}kcal", t("res_unit_days", days=days), status)
            elif r.type == ResourceType.FIRE:
                name = t("res_fire_table")
                if is_offline:
                    res_table.add_row(name, f"[dim]{t('resource_offline')}[/]", "--", "◇")
                    continue
                status = "🟢" if r.current_amount > 20 else "🟡" if r.current_amount > 10 else "🔴"
                fire_avail = t("res_unit_days", days=r.current_amount / r.daily_consumption) if r.daily_consumption > 0 else t("res_infinite")
                res_table.add_row(name, t("fire_unit", count=r.current_amount), fire_avail, status)
            elif r.type == ResourceType.STORAGE:
                name = t("res_storage_table")
                if is_offline:
                    res_table.add_row(name, f"[dim]{t('resource_offline')}[/]", "--", "◇")
                    continue
                total = r.daily_consumption
                used = r.daily_intake
                pct = ((total - used) / total * 100) if total > 0 else 0
                status = "🟢" if pct > 30 else "🟡" if pct > 10 else "🔴"
                res_table.add_row(name, f"{used:.0f}/{total:.0f}GB", f"{pct:.1f}%", status)

        self.console.print(res_table)

        has_data = any(r.current_amount > 0 for r in resources)
        if not has_data:
            self.console.print(f"[dim]{t('resource_offline_hint')}[/]")
        else:
            self.console.print(f"[dim]{t('data_disclaimer')}[/]")

        tasks = planner.get_all_active()
        if tasks:
            task_table = Table(title=t("task_title"), show_header=True, header_style="bold")
            task_table.add_column(t("field_id"), style="dim")
            task_table.add_column(t("field_phase_col"), justify="center")
            task_table.add_column(t("field_task"))
            task_table.add_column(t("field_status"), justify="center")
            for task in tasks:
                status_icon = {"pending": "⬜", "in_progress": "🔄", "completed": "✅", "failed": "❌"}.get(task.status, "❓")
                task_table.add_row(task.id, f"Phase {task.phase}", task.title, status_icon)
            self.console.print(task_table)


class ResourceCommand(BaseCommand):
    COMMAND_NAME = "resource"
    ALIASES = ("资源",)

    def execute(self, args: list[str]) -> None:
        resource_mgr = self.container.require("resource_manager")
        self.console.print(resource_mgr.get_resource_summary())


class LangCommand(BaseCommand):
    COMMAND_NAME = "lang"
    ALIASES = ("语言", "language")

    def execute(self, args: list[str]) -> None:
        from allspark.i18n import set_language, get_language

        if not args:
            self.console.print(f"[dim]{t('lang_current', lang=get_language())}[/dim]")
            self.console.print(f"[dim]{t('lang_switched', lang=get_language())}[/dim]")
            return

        lang = args[0].lower()
        if lang in ("zh", "cn", "中文"):
            set_language("zh")
            self.console.print(f"[green]{t('lang_switched', lang='中文')}[/]")
        elif lang in ("en", "eng", "english"):
            set_language("en")
            self.console.print(f"[green]{t('lang_switched', lang='English')}[/]")
        else:
            self.console.print(f"[red]{t('lang_unsupported', lang=lang)}[/]")


class SetCommand(BaseCommand):
    COMMAND_NAME = "set"
    ALIASES = ("设置",)

    def execute(self, args: list[str]) -> None:
        resource_mgr = self.container.require("resource_manager")

        if len(args) < 2:
            self.console.print(f"[dim]{t('set_usage_msg')}")
            self.console.print(f"{t('set_types_msg')}")
            self.console.print(f"{t('set_example_msg')}")
            self.console.print(t("set_example_zh"))
            return

        type_map = {
            "power": ResourceType.POWER,
            "water": ResourceType.WATER,
            "food": ResourceType.FOOD,
            "fire": ResourceType.FIRE,
            "storage": ResourceType.STORAGE,
            "电力": ResourceType.POWER,
            "水": ResourceType.WATER,
            "食物": ResourceType.FOOD,
            "火": ResourceType.FIRE,
            "存储": ResourceType.STORAGE,
        }

        rtype_str = args[0].lower()
        rtype = type_map.get(rtype_str)
        if rtype is None:
            self.console.print(f"[red]{t('unknown_resource_type', type=args[0])}[/]")
            return

        try:
            amount = float(args[1])
            consumption = float(args[2]) if len(args) > 2 else None
            intake = float(args[3]) if len(args) > 3 else None
        except ValueError:
            self.console.print(f"[red]{t('invalid_numeric')}[/]")
            return

        resource_mgr.update_resource(rtype, amount, consumption, intake)
        updated = self.db.get_resource(rtype)
        self.console.print(f"[green]{t('set_updated_with_unit', type=t(f'resource_{rtype.value}'), amount=updated.current_amount, unit=updated.unit)}[/]")
        self.console.print(t("set_remaining_hours", hours=updated.estimated_remaining_hours))

        warnings = resource_mgr.check_warnings()
        if warnings:
            for w in warnings:
                style = "bold red" if w["level"] == "critical" else "yellow"
                self.console.print(f"  [{style}]{w['message']}[/]")


class ExitCommand(BaseCommand):
    COMMAND_NAME = "exit"
    ALIASES = ("退出", "quit", "q")

    def __init__(self, container: ServiceContainer, cli_instance):
        super().__init__(container)
        self.cli = cli_instance

    def execute(self, args: list[str]) -> None:
        self.console.print(t("exit_message"))
        self.cli.running = False
