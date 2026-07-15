from rich.table import Table

from allspark.commands.base import BaseCommand
from allspark.container import ServiceContainer
from allspark.core.i18n import render, t
from allspark.core.models import OperatingMode, ResourceType
from allspark.services.resource_manager import ResourceValidationError


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
            is_offline = not r.amount_known
            rates_complete = resource_mgr.has_complete_rate_data(r)

            if r.type == ResourceType.POWER:
                name = t("res_power_table")
                if is_offline:
                    res_table.add_row(name, f"[dim]{t('resource_offline')}[/]", "--", "◇")
                    continue
                if not rates_complete:
                    avail = t("resource_remaining_unknown")
                    status = "◇"
                elif r.estimated_remaining_hours < 0:
                    avail = t("res_sustained")
                    status = "🟢"
                else:
                    avail = t("res_unit_hours", hours=r.estimated_remaining_hours)
                    status = "🟢" if r.estimated_remaining_hours > 72 else "🟡" if r.estimated_remaining_hours > 24 else "🔴"
                res_table.add_row(name, f"{r.current_amount:.0f}Wh", avail, status)
            elif r.type == ResourceType.WATER:
                name = t("res_water_table")
                if is_offline:
                    res_table.add_row(name, f"[dim]{t('resource_offline')}[/]", "--", "◇")
                    continue
                if not rates_complete:
                    avail = t("resource_remaining_unknown")
                    status = "◇"
                elif r.estimated_remaining_hours < 0:
                    avail = t("res_sustained")
                    status = "🟢"
                else:
                    days = r.estimated_remaining_hours / 24.0
                    avail = t("res_unit_days", days=days)
                    status = "🟢" if days > 7 else "🟡" if days > 3 else "🔴"
                res_table.add_row(name, f"{r.current_amount:.1f}L", avail, status)
            elif r.type == ResourceType.FOOD:
                name = t("res_food_table")
                if is_offline:
                    res_table.add_row(name, f"[dim]{t('resource_offline')}[/]", "--", "◇")
                    continue
                if not rates_complete:
                    days = 0.0
                    avail = t("resource_remaining_unknown")
                    status = "◇"
                elif r.estimated_remaining_hours < 0:
                    avail = t("res_sustained")
                    status = "🟢"
                else:
                    days = r.estimated_remaining_hours / 24.0
                    avail = t("res_unit_days", days=days)
                    status = "🟢" if days > 14 else "🟡" if days > 5 else "🔴"
                res_table.add_row(name, f"{r.current_amount:.0f}kcal", avail, status)
            elif r.type == ResourceType.FIRE:
                name = t("res_fire_table")
                if is_offline:
                    res_table.add_row(name, f"[dim]{t('resource_offline')}[/]", "--", "◇")
                    continue
                status = "◇" if not rates_complete else "🟢" if r.current_amount > 20 else "🟡" if r.current_amount > 10 else "🔴"
                fire_avail = t("resource_remaining_unknown") if not rates_complete else t("res_unit_days", days=r.estimated_remaining_hours / 24.0) if r.estimated_remaining_hours >= 0 else t("res_sustained")
                res_table.add_row(name, t("fire_unit", count=r.current_amount), fire_avail, status)
            elif r.type == ResourceType.STORAGE:
                name = t("res_storage_table")
                if is_offline:
                    res_table.add_row(name, f"[dim]{t('resource_offline')}[/]", "--", "◇")
                    continue
                if not rates_complete:
                    res_table.add_row(
                        name,
                        f"{r.current_amount:.1f}GB",
                        t("resource_remaining_unknown"),
                        "◇",
                    )
                else:
                    remaining = (
                        t("res_sustained")
                        if r.estimated_remaining_hours < 0
                        else t("res_unit_hours", hours=r.estimated_remaining_hours)
                    )
                    res_table.add_row(name, f"{r.current_amount:.1f}GB", remaining, "◇")

        self.console.print(res_table)

        has_data = any(r.amount_known for r in resources)
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
                task_table.add_row(task.id, f"Phase {task.phase}", render(task.title), status_icon)
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
        from allspark.core.i18n import get_language, set_language

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

        if args[1].lower() in ("unknown", "未知"):
            try:
                current = self.db.get_resource(rtype)
                people_count = (
                    args[2]
                    if len(args) > 2
                    else current.people_count
                    if current is not None
                    else 1
                )
                people_count_known = (
                    len(args) > 2
                    or (current.people_count_known if current is not None else False)
                )
                input_kind = args[3].lower() if len(args) > 3 else "observed"
                if input_kind not in {"observed", "estimate", "观测", "估算"}:
                    raise ResourceValidationError("input_kind", "invalid_input_kind")
                source = "estimate" if input_kind in {"estimate", "估算"} else "user_input"
                resource_mgr.mark_unknown(
                    rtype,
                    people_count=people_count,
                    people_count_known=people_count_known,
                    source=source,
                )
            except (ValueError, ResourceValidationError) as exc:
                reason = exc.reason if isinstance(exc, ResourceValidationError) else "not_numeric"
                self.console.print(f"[red]{t(f'error_resource_{reason}', field='people_count')}[/]")
                return
            self.console.print(t("resource_marked_unknown", type=t(f"resource_{rtype.value}")))
            return

        try:
            amount = float(args[1])
            consumption = float(args[2]) if len(args) > 2 else None
            intake = float(args[3]) if len(args) > 3 else None
            current = self.db.get_resource(rtype)
            people_count = (
                args[4]
                if len(args) > 4
                else current.people_count
                if current is not None
                else 1
            )
            people_count_known = (
                len(args) > 4
                or (current.people_count_known if current is not None else False)
            )
            capacity = (
                float(args[5])
                if rtype == ResourceType.STORAGE and len(args) > 5
                else None
            )
            kind_index = 6 if rtype == ResourceType.STORAGE else 5
            input_kind = args[kind_index].lower() if len(args) > kind_index else "observed"
        except ValueError:
            self.console.print(f"[red]{t('invalid_numeric')}[/]")
            return

        try:
            if input_kind not in {"observed", "estimate", "观测", "估算"}:
                raise ResourceValidationError("input_kind", "invalid_input_kind")
            source = "estimate" if input_kind in {"estimate", "估算"} else "user_input"
            resource_mgr.update_resource(
                rtype,
                amount,
                consumption,
                intake,
                people_count=people_count,
                people_count_known=people_count_known,
                capacity=capacity,
                source=source,
            )
        except ResourceValidationError as exc:
            self.console.print(
                f"[red]{t(f'error_resource_{exc.reason}', field=exc.field)}[/]"
            )
            return
        updated = self.db.get_resource(rtype)
        if updated is None:
            return
        self.console.print(f"[green]{t('set_updated_with_unit', type=t(f'resource_{rtype.value}'), amount=updated.current_amount, unit=updated.unit)}[/]")
        remaining_status = resource_mgr.remaining_status(updated)
        if remaining_status == "finite":
            self.console.print(t("set_remaining_hours", hours=updated.estimated_remaining_hours))
        elif remaining_status == "sustained":
            self.console.print(t("res_sustained"))
        else:
            self.console.print(f"[dim]{t('resource_remaining_unknown')}[/]")

        warnings = resource_mgr.check_warnings()
        if warnings:
            for w in warnings:
                style = "bold red" if w["level"] == "critical" else "yellow"
                self.console.print(f"  [{style}]{w['message']}[/]")


class ExitCommand(BaseCommand):
    COMMAND_NAME = "exit"
    ALIASES = ("退出", "quit", "q")

    def __init__(self, container: ServiceContainer, cli_instance=None):
        super().__init__(container)
        self.cli = cli_instance

    def execute(self, args: list[str]) -> None:
        self.console.print(t("exit_message"))
        self.cli.running = False
