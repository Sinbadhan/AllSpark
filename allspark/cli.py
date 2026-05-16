import sys
import shlex

from rich.console import Console
from rich.panel import Panel
from allspark import __version__
from rich.table import Table
from rich.text import Text

from allspark.database import Database
from allspark.rule_engine import RuleEngine
from allspark.resource_manager import ResourceManager
from allspark.knowledge_engine import KnowledgeEngine
from allspark.map_system import MapSystem
from allspark.models import ResourceType, OperatingMode
from allspark.i18n import t, set_language, get_language, detect_language, init_language
from allspark.init_wizard import run_init_wizard
from allspark.hardware import FeatureFlags


console = Console()


class SparkCLI:
    def __init__(self, db_path=None):
        self.db = Database(db_path)
        init_language(self.db)
        self.engine = None
        self.running = True
        self.init_result = None
        self._flags = None

    def _lazy_init(self, attr: str, factory):
        if not hasattr(self, attr) or getattr(self, attr) is None:
            setattr(self, attr, factory())
        return getattr(self, attr)

    @staticmethod
    def _t(zh: str, en: str) -> str:
        return zh if get_language() == "zh" else en

    def run(self):
        if not self.db.is_initialized():
            self.init_result = run_init_wizard(self.db)
            if self.init_result and "hardware" in self.init_result:
                self._flags = self.init_result["hardware"].get("flags")

        self.engine = RuleEngine(self.db, flags=self._flags)
        self.engine.initialize()
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

    def _print_banner(self):
        banner = Text()
        banner.append(f"ALLSPARK v{__version__}\n", style="bold red")
        banner.append(t("app_subtitle") + "\n", style="dim")
        banner.append("━━━━━━━━━━━━━━━━━━━━━━━━━━", style="dim")
        banner.append(f"\n{t('app_mission')}", style="italic")
        console.print(Panel(banner, border_style="red", padding=(1, 2)))

    def _print_initial_status(self):
        warnings = self.engine.resource_mgr.check_warnings()
        mode, changed = self.engine.resource_mgr.update_operating_mode()
        mode_names = {
            OperatingMode.PROACTIVE: t("mode_proactive"),
            OperatingMode.STANDARD: t("mode_standard"),
            OperatingMode.ECONOMY: t("mode_economy"),
            OperatingMode.HIBERNATION: t("mode_hibernation"),
            OperatingMode.RECOVERY: t("mode_recovery"),
        }
        self.engine.personality.determine_mode(
            mode, warnings,
            self.engine.survival.assess()["phase"]
        )
        greeting = self.engine.personality.greet()
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

        resources = self.engine.resource_mgr.get_all_resources()
        has_data = any(r.current_amount > 0 for r in resources)
        if not has_data:
            console.print(f"\n[dim]{t('resource_offline_hint')}[/]")

        console.print(f"\n[dim]{t('help_help')}[/]")

        self._phase7_post_init()

    def _phase7_post_init(self):
        if hasattr(self.engine, 'timeline') and self.engine.timeline:
            self.engine.timeline.add_event(
                event_type="system_event",
                title=t("spark_activated"),
                description=t("spark_activated_desc"),
            )

        if hasattr(self.engine, 'goal_engine') and self.engine.goal_engine:
            active_goals = self.engine.goal_engine.get_active_goals()
            if not active_goals:
                console.print(f"\n[bold blue]{t('goals_auto_generating')}[/]")
                goals = self.engine.goal_engine.auto_generate_goals()
                if goals:
                    console.print(f"[green]{t('goals_auto_generated', count=len(goals))}[/]")
                    for g in goals[:3]:
                        icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(g.priority, "⚪")
                        console.print(f"  {icon} [{g.category}] {g.title}")
                    if len(goals) > 3:
                        console.print(f"  {t('goals_and_more', count=len(goals) - 3)}")
                else:
                    console.print(f"[dim]{t('goals_no_urgent')}[/]")

        if hasattr(self.engine, 'daily_briefing') and self.engine.daily_briefing:
            console.print(f"\n[bold cyan]{t('briefing_generating')}[/]")
            briefing = self.engine.daily_briefing.generate()
            console.print(briefing)

    def _process_command(self, user_input: str):
        parts = user_input.split()
        if not parts:
            return
        cmd = parts[0].lower()

        if cmd in ("退出", "exit", "quit", "q"):
            console.print(t("exit_message"))
            self.running = False
            return

        if cmd in ("帮助", "help", "h", "?"):
            console.print(self.engine._handle_help())
            return

        if cmd in ("语言", "lang", "language"):
            self._handle_lang(parts[1:] if len(parts) > 1 else [])
            return

        if cmd in ("模块", "module", "modules", "mod"):
            self._handle_module(parts[1:] if len(parts) > 1 else [])
            return

        if cmd in ("llm", "ai", "模型"):
            self._handle_llm(parts[1:] if len(parts) > 1 else [])
            return

        if cmd in ("经验", "exp", "experience"):
            self._handle_experience(parts[1:] if len(parts) > 1 else [])
            return

        if cmd in ("skf", "知识包"):
            self._handle_skf(parts[1:] if len(parts) > 1 else [])
            return

        if cmd in ("验证", "verify"):
            self._handle_verify(parts[1:] if len(parts) > 1 else [])
            return

        if cmd in ("网络", "network", "net"):
            self._handle_network(parts[1:] if len(parts) > 1 else [])
            return

        if cmd in ("视觉", "vision", "识别"):
            self._handle_vision(parts[1:] if len(parts) > 1 else [])
            return

        if cmd in ("社区", "community", "gov", "成员"):
            self._handle_governance(parts[1:] if len(parts) > 1 else [])
            return

        if cmd in ("交易", "trade"):
            self._handle_trade(parts[1:] if len(parts) > 1 else [])
            return

        if cmd in ("电力", "power", "电量"):
            self._handle_power(parts[1:] if len(parts) > 1 else [])
            return

        if cmd in ("传感器", "sensor", "sensors"):
            self._handle_sensor(parts[1:] if len(parts) > 1 else [])
            return

        if cmd in ("固化", "preserve", "backup", "备份"):
            self._handle_preserve(parts[1:] if len(parts) > 1 else [])
            return

        if cmd == "map":
            self._handle_map(parts[1:] if len(parts) > 1 else [])
            return

        if cmd in ("设置", "set"):
            self._handle_set(parts[1:])
            return

        if cmd in ("任务", "task", "tasks"):
            self._handle_task(parts[1:])
            return

        if cmd in ("知识", "know", "knowledge"):
            self._handle_knowledge(parts[1:])
            return

        if cmd in ("状态", "status"):
            self._handle_status()
            return

        if cmd in ("资源", "resource"):
            self._handle_resources()
            return

        if cmd in ("目标", "goals", "goal"):
            self._handle_goal(parts[1:] if len(parts) > 1 else [])
            return

        if cmd in ("重置", "reset"):
            self._handle_reset(parts[1:] if len(parts) > 1 else [])
            return

        if cmd in ("简报", "briefing", "daily"):
            self._handle_briefing()
            return

        if cmd in ("时间线", "timeline", "时间"):
            self._handle_timeline(parts[1:] if len(parts) > 1 else [])
            return

        if cmd in ("日记", "diary"):
            self._handle_diary(parts[1:] if len(parts) > 1 else [])
            return

        if cmd in ("天气", "weather"):
            self._handle_weather(parts[1:] if len(parts) > 1 else [])
            return

        if cmd in ("心理", "psychology", "mood"):
            self._handle_psychology(parts[1:] if len(parts) > 1 else [])
            return

        if cmd in ("定位", "gps", "位置"):
            self._handle_gps(parts[1:] if len(parts) > 1 else [])
            return

        if cmd in ("环境", "env", "environment"):
            self._handle_environment()
            return

        if cmd in ("语音", "voice", "录音"):
            self._handle_voice(parts[1:] if len(parts) > 1 else [])
            return

        response = self.engine.process_input(user_input)
        console.print(response)

    def _handle_status(self):
        assessment = self.engine.survival.assess()
        mode, _ = self.engine.resource_mgr.update_operating_mode()
        warnings = self.engine.resource_mgr.check_warnings()

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

        console.print(status_table)

        if warnings:
            console.print(f"\n[bold]{t('warnings_label')}[/]")
            for w in warnings:
                style = "bold red" if w["level"] == "critical" else "yellow"
                console.print(f"  [{style}]{w['message']}[/]")

        resources = self.engine.resource_mgr.get_all_resources()
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

        console.print(res_table)

        has_data = any(r.current_amount > 0 for r in resources)
        if not has_data:
            console.print(f"[dim]{t('resource_offline_hint')}[/]")
        else:
            console.print(f"[dim]{t('data_disclaimer')}[/]")

        tasks = self.engine.planner.get_all_active()
        if tasks:
            task_table = Table(title=t("task_title"), show_header=True, header_style="bold")
            task_table.add_column(t("field_id"), style="dim")
            task_table.add_column(t("field_phase_col"), justify="center")
            task_table.add_column(t("field_task"))
            task_table.add_column(t("field_status"), justify="center")
            for task in tasks:
                status_icon = {"pending": "⬜", "in_progress": "🔄", "completed": "✅", "failed": "❌"}.get(task.status, "❓")
                task_table.add_row(task.id, f"Phase {task.phase}", task.title, status_icon)
            console.print(task_table)

    def _handle_resources(self):
        console.print(self.engine.resource_mgr.get_resource_summary())

    def _handle_map(self, args: list[str]):
        if not args:
            console.print(self.engine.maps.format_map())
            return

        subcmd = args[0].lower()

        if subcmd == "add":
            console.print(f"[bold]{t('add_to_map')}[/]")
            name = console.input(t("map_name_prompt")).strip()
            if not name:
                console.print(f"[dim]{t('map_add_cancelled')}[/]")
                return
            poi_type = console.input(t("map_type_prompt")).strip() or "other"
            desc = console.input(t("map_desc_prompt")).strip()
            dist_str = console.input(t("map_dist_prompt")).strip()
            dist = float(dist_str) if dist_str else 0.0
            direction = console.input(t("map_dir_prompt")).strip()
            notes = console.input(t("map_notes_prompt")).strip()

            poi = self.engine.maps.add_poi(
                name=name, poi_type=poi_type, description=desc,
                distance_km=dist, direction=direction, notes=notes
            )
            console.print(f"[green]{t('map_added', name=poi.name, id=poi.id)}[/]")

        elif subcmd == "remove" and len(args) > 1:
            self.engine.maps.remove_poi(args[1])
            console.print(f"[green]{t('map_deleted', id=args[1])}[/]")

        elif subcmd in ("water", "shelter", "food", "danger", "resource", "camp", "medical"):
            pois = self.engine.maps.get_by_type(subcmd)
            if pois:
                for p in pois:
                    console.print(self.engine.maps.format_poi_detail(p))
                    console.print("")
            else:
                console.print(f"[dim]{t('map_no_type_locations', type=subcmd)}[/]")

        else:
            console.print(f"[dim]{t('map_usage_msg')}[/]")

    def _handle_set(self, args: list[str]):
        if len(args) < 2:
            console.print(f"[dim]{t('set_usage_msg')}")
            console.print(f"{t('set_types_msg')}")
            console.print(f"{t('set_example_msg')}")
            console.print("      设置 water 10 2")
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
            console.print(f"[red]{t('unknown_resource_type', type=args[0])}[/]")
            return

        try:
            amount = float(args[1])
            consumption = float(args[2]) if len(args) > 2 else None
            intake = float(args[3]) if len(args) > 3 else None
        except ValueError:
            console.print(f"[red]{t('invalid_numeric')}[/]")
            return

        self.engine.resource_mgr.update_resource(rtype, amount, consumption, intake)
        updated = self.db.get_resource(rtype)
        console.print(f"[green]{t('set_updated_with_unit', type=rtype.value, amount=updated.current_amount, unit=updated.unit)}[/]")
        console.print(t("set_remaining_hours", hours=updated.estimated_remaining_hours))

        warnings = self.engine.resource_mgr.check_warnings()
        if warnings:
            for w in warnings:
                style = "bold red" if w["level"] == "critical" else "yellow"
                console.print(f"  [{style}]{w['message']}[/]")

    def _handle_task(self, args: list[str]):
        if not args:
            tasks = self.engine.planner.get_all_active()
            if not tasks:
                assessment = self.engine.survival.assess()
                tasks = self.engine.planner.suggest_tasks(assessment["resources"])
            console.print(self.engine.planner.format_tasks(tasks))
            return

        subcmd = args[0].lower()
        if subcmd in ("完成", "done", "complete") and len(args) > 1:
            self.engine.planner.complete_task(args[1])
            console.print(f"[green]{t('task_done_msg', id=args[1])}[/]")
        elif subcmd in ("开始", "start") and len(args) > 1:
            self.engine.planner.start_task(args[1])
            console.print(f"[green]{t('task_start_msg', id=args[1])}[/]")
        elif subcmd in ("失败", "fail") and len(args) > 1:
            self.engine.planner.fail_task(args[1])
            console.print(f"[yellow]{t('task_fail_msg', id=args[1])}[/]")
        else:
            console.print(f"[dim]{t('task_usage_msg')}[/]")

    def _handle_knowledge(self, args: list[str]):
        if not args:
            categories = self.engine.knowledge.get_categories()
            console.print(f"[bold]{t('knowledge_categories')}[/]")
            for cat in categories:
                subcats = self.engine.knowledge.get_subcategories(cat)
                console.print(f"  {cat}: {', '.join(subcats)}")
            console.print(f"\n[dim]{t('knowledge_usage')}[/]")
            return

        if len(args) >= 2:
            entries = self.engine.knowledge.get_by_category(args[0], args[1])
        else:
            entries = self.engine.knowledge.search(" ".join(args), limit=10)

        if not entries:
            console.print(f"[dim]{t('no_knowledge', topic=' '.join(args))}[/]")
            return

        for entry in entries:
            console.print(Panel(
                self.engine.knowledge.format_entry(entry),
                title=f"Tier {entry.priority} | {entry.category}/{entry.subcategory}",
                border_style="green" if entry.priority == 0 else "yellow" if entry.priority == 1 else "blue"
            ))

    def _handle_lang(self, args: list[str]):
        if not args:
            console.print(f"[dim]Current language: {get_language()} | Supported: zh, en[/dim]")
            console.print(f"[dim]{t('lang_switched', lang=get_language())}[/dim]")
            return

        lang = args[0].lower()
        if lang in ("zh", "cn", "中文"):
            set_language("zh")
            console.print(f"[green]{t('lang_switched', lang='中文')}[/]")
        elif lang in ("en", "eng", "english"):
            set_language("en")
            console.print(f"[green]{t('lang_switched', lang='English')}[/]")
        else:
            console.print(f"[red]{t('lang_unsupported', lang=lang)}[/]")

    def _handle_module(self, args: list[str]):
        registry = self.engine.registry
        lang = get_language()

        if not args:
            console.print(registry.format_status(lang=lang))
            disabled = registry.get_disabled_by_hardware()
            if disabled:
                console.print(f"\n[dim]{t('module_disabled_hw', modules=', '.join(disabled))}[/]")
                console.print(f"[dim]{t('module_enable_hint')}[/]")
            return

        subcmd = args[0].lower()

        if subcmd in ("enable", "启用") and len(args) > 1:
            mod_name = args[1]
            if not registry.is_available(mod_name):
                console.print(f"[red]{t('module_not_supported', name=mod_name)}[/]")
                return
            registry.enable(mod_name)
            registry.save_to_db(self.db)
            console.print(f"[green]{t('module_enabled', name=mod_name)}[/]")

        elif subcmd in ("disable", "禁用") and len(args) > 1:
            mod_name = args[1]
            if registry.is_loaded(mod_name):
                mod_def = registry._modules.get(mod_name)
                if mod_def and mod_def.is_core:
                    console.print(f"[red]{t('module_core_no_disable', name=mod_name)}[/]")
                    return
            registry.disable(mod_name)
            registry.save_to_db(self.db)
            console.print(f"[green]{t('module_disabled', name=mod_name)}[/]")

        elif subcmd in ("list", "列表", "ls"):
            console.print(registry.format_status(lang=lang))

        else:
            console.print(f"[dim]{t('module_usage')}[/]")

    def _handle_llm(self, args: list[str]):
        lang = get_language()
        llm = self.engine.llm

        if not args:
            status = llm.get_status()
            table = Table(title=t("title_llm_status"))
            table.add_column("Item", style="cyan")
            table.add_column("Value")
            table.add_row("Available", "✅ Yes" if status["available"] else "❌ No")
            table.add_row("Model", status["model_name"])
            table.add_row("Path", status.get("model_path") or "Not loaded")
            if status.get("error"):
                table.add_row("Error", f"[red]{status['error']}[/]")
            console.print(table)
            return

        subcmd = args[0].lower()

        if subcmd in ("load", "加载"):
            with console.status(t("llm_loading")):
                ok = llm.load()
            if ok:
                self.engine.registry.register("llm", llm)
                self.engine.registry.save_to_db(self.db)
                console.print(f"[green]{t('llm_loaded', model=llm.model_name)}[/]")
            else:
                console.print(f"[red]{llm.error}[/]")
            return

        if subcmd in ("chat", "问") and len(args) > 1:
            message = " ".join(args[1:])
            if not llm.available:
                console.print(f"[red]{t('llm_not_available')}[/]")
                return
            with console.status(t("llm_thinking")):
                response = llm.survival_chat(message, phase=self.engine.survival.assess().phase)
            console.print(Panel(response, title="🤖 AllSpark AI"))
            return

        console.print(f"[dim]{t('llm_usage')}[/]")

    def _handle_governance(self, args: list[str]):
        lang = get_language()
        from allspark.governance import GovernanceEngine

        gov = self._lazy_init('_gov', lambda: GovernanceEngine(db=self.db, llm_engine=self.engine.llm if self.engine else None))

        if not args:
            status = gov.get_status()
            table = Table(title=t("title_governance"))
            table.add_column(t("field_item"), style="cyan")
            table.add_column(t("field_value"))
            table.add_row(t("field_total"), str(status["total_members"]))
            table.add_row(t("field_has_commander"), "✅" if status["has_commander"] else "❌")
            table.add_row(t("field_open_conflicts"), str(status["open_conflicts"]))
            if status.get("roles"):
                table.add_row(t("field_role_dist"), ", ".join(f"{k}:{v}" for k, v in status["roles"].items()))
            console.print(table)

            console.print(f"\n[dim]{t('governance_usage')}[/]")
            return

        sub = args[0].lower()

        if sub in ("add", "添加"):
            name = args[1] if len(args) > 1 else "Unknown"
            role = args[2] if len(args) > 2 else "executor"
            member = gov.add_member(name, role=role)
            console.print(f"[green]✅ Added member: {member.name} ({member.id}) role={member.role}[/]")

        elif sub in ("remove", "移除", "删除"):
            mid = args[1] if len(args) > 1 else ""
            if gov.remove_member(mid):
                console.print(f"[green]✅ Member {mid} removed[/]")
            else:
                console.print(f"[red]❌ Cannot remove {mid} (not found or last commander)[/]")

        elif sub in ("role", "角色", "assign"):
            mid = args[1] if len(args) > 1 else ""
            role = args[2] if len(args) > 2 else ""
            if gov.assign_role(mid, role):
                console.print(f"[green]✅ Role updated: {mid} → {role}[/]")
            else:
                console.print(f"[red]❌ Cannot assign role to {mid}[/]")

        elif sub in ("list", "列表", "ls"):
            members = gov.get_all_members()
            if not members:
                console.print("[yellow]No community members[/]")
                return
            table = Table(title=t("title_governance"))
            table.add_column(t("field_id"), style="cyan")
            table.add_column(t("field_name"))
            table.add_column(t("field_role"))
            table.add_column(t("field_domain"))
            table.add_column(t("field_health"))
            table.add_column(t("field_score"))
            for m in members:
                table.add_row(m.id, m.name, m.role + (" ⭐" if m.is_commander else ""),
                              ", ".join(m.domains) or "-", m.health_status,
                              f"{m.contribution_score:.1f}")
            console.print(table)

        elif sub in ("assess", "评估"):
            result = gov.assess_organization()
            table = Table(title=t("title_governance"))
            table.add_column(t("field_item"), style="cyan")
            table.add_column(t("field_value"))
            table.add_row(t("field_total"), str(result["total_members"]))
            table.add_row(t("field_has_commander"), "✅" if result["has_commander"] else "❌")
            table.add_row(t("field_role_dist"), str(result["role_distribution"]))
            table.add_row(t("field_domain_coverage"), ", ".join(result["domain_coverage"]) or "None")
            if result["missing_domains"]:
                table.add_row(t("field_missing_domains"), "[red]" + ", ".join(result["missing_domains"]) + "[/]")
            console.print(table)
            if result["recommendations"]:
                console.print(f"[bold]{t('recommendations')}[/]")
                for r in result["recommendations"]:
                    console.print(f"  ⚠ {r}")

        elif sub in ("recommend", "推荐"):
            recs = gov.recommend_roles()
            if not recs:
                console.print(f"[green]{t('no_role_changes')}[/]")
            else:
                for r in recs:
                    console.print(f"  📋 {r['member_name']} ({r['member_id']}): {r['current_role']} → {r['recommended_role']}")
                    console.print(f"     [dim]{r['reason']}[/]")

        elif sub in ("value", "价值"):
            mid = args[1] if len(args) > 1 else ""
            result = gov.calculate_survival_value(mid)
            if not result:
                console.print(f"[red]Member {mid} not found[/]")
                return
            table = Table(title=t("survival_value_title", name=result['member_name']))
            table.add_column(t("field_dimension"), style="cyan")
            table.add_column(t("field_score"))
            for dim, val in result["dimensions"].items():
                bar = "█" * int(val * 10) + "░" * (10 - int(val * 10))
                table.add_row(dim, f"{val:.3f} {bar}")
            table.add_row(f"[bold]{t('field_composite')}[/]", f"[bold]{result['composite_value']:.3f}[/]")
            console.print(table)
            console.print(f"[dim]{result['disclaimer']}[/]")

        elif sub in ("conflict", "冲突"):
            title = args[1] if len(args) > 1 else "Untitled"
            parties = args[2:] if len(args) > 2 else []
            conflict = gov.create_conflict(title, "", parties)
            console.print(f"[yellow]⚠ Conflict recorded: {conflict.id}[/]")

        elif sub in ("mediate", "调解"):
            cid = args[1] if len(args) > 1 else ""
            result = gov.mediate_conflict(cid)
            if not result:
                console.print(f"[red]Conflict {cid} not found[/]")
                return
            console.print(f"[cyan]📋 Mediation strategies for {result['conflict_id']}:[/]")
            for s in result["strategies"]:
                console.print(f"  • {s['type']}: {s['description']}")
            if "ai_suggestion" in result:
                console.print(f"\n[bold]AI Suggestion:[/]\n{result['ai_suggestion']}")

        elif sub in ("resolve", "解决"):
            cid = args[1] if len(args) > 1 else ""
            resolution = " ".join(args[2:]) if len(args) > 2 else "Resolved"
            if gov.resolve_conflict(cid, resolution):
                console.print(f"[green]✅ Conflict {cid} resolved[/]")
            else:
                console.print(f"[red]❌ Cannot resolve {cid}[/]")

        else:
            console.print(f"[yellow]Unknown governance command: {sub}[/]")

    def _handle_trade(self, args: list[str]):
        lang = get_language()
        from allspark.trade_engine import TradeEngine

        trade = self._lazy_init('_trade_engine', lambda: TradeEngine(db=self.db))

        if not args:
            status = trade.get_status()
            table = Table(title=t("title_trade"))
            table.add_column(t("field_item"), style="cyan")
            table.add_column(t("field_value"))
            table.add_row(t("field_total_trades"), str(status["total_trades"]))
            table.add_row(t("field_active"), str(status["active_trades"]))
            table.add_row(t("field_completed"), str(status["completed_trades"]))
            console.print(table)

            console.print(f"\n[dim]{t('trade_usage')}[/]")
            return

        sub = args[0].lower()

        if sub in ("status", "状态"):
            status = trade.get_status()
            table = Table(title=t("title_trade"))
            table.add_column(t("field_item"), style="cyan")
            table.add_column(t("field_value"))
            table.add_row(t("field_total_trades"), str(status["total_trades"]))
            table.add_row(t("field_active"), str(status["active_trades"]))
            table.add_row(t("field_completed"), str(status["completed_trades"]))
            console.print(table)
            console.print(f"\n[dim]{t('trade_usage')}[/]")
            return

        if sub in ("propose", "提议", "发起"):
            target = args[1] if len(args) > 1 else ""
            offer_ids = args[2].split(",") if len(args) > 2 else []
            request_ids = args[3].split(",") if len(args) > 3 else []
            offer = trade.propose_trade("local", target, offer_ids, request_ids)
            console.print(f"[green]✅ Trade proposed: {offer.id}[/]")
            console.print(f"  Offer: {offer.offer_knowledge_ids}")
            console.print(f"  Request: {offer.request_knowledge_ids}")

        elif sub in ("accept", "接受"):
            tid = args[1] if len(args) > 1 else ""
            result = trade.accept_trade(tid)
            if result.get("status") == "ok":
                console.print(f"[green]✅ Trade completed: received {result['received_count']} entries[/]")
                if result.get("rejected_count", 0) > 0:
                    console.print(f"[yellow]⚠ {result['rejected_count']} entries rejected (conflict)[/]")
            else:
                console.print(f"[red]❌ {result.get('message', 'Trade failed')}[/]")

        elif sub in ("reject", "拒绝"):
            tid = args[1] if len(args) > 1 else ""
            if trade.reject_trade(tid):
                console.print(f"[yellow]Trade {tid} rejected[/]")
            else:
                console.print(f"[red]Trade {tid} not found[/]")

        elif sub in ("cancel", "取消"):
            tid = args[1] if len(args) > 1 else ""
            if trade.cancel_trade(tid):
                console.print(f"[yellow]Trade {tid} cancelled[/]")
            else:
                console.print(f"[red]Cannot cancel {tid}[/]")

        elif sub in ("evaluate", "评估"):
            tid = args[1] if len(args) > 1 else ""
            result = trade.evaluate_trade(tid)
            if not result:
                console.print(f"[red]Trade {tid} not found[/]")
                return
            table = Table(title=t("trade_eval_title", id=tid))
            table.add_column(t("field_item"), style="cyan")
            table.add_column(t("field_value"))
            table.add_row(t("field_evaluation"), result["evaluation"])
            table.add_row(t("field_reason"), result["reason"])
            table.add_row(t("field_your_value"), str(result["your_offer_value"]))
            table.add_row(t("field_their_value"), str(result["their_offer_value"]))
            table.add_row(t("field_new_knowledge"), str(result["new_knowledge_count"]))
            console.print(table)

        elif sub in ("list", "列表", "ls"):
            trades = trade.get_active_trades()
            if not trades:
                console.print(f"[green]{t('no_active_trades')}[/]")
                return
            table = Table(title=t("active_trades"))
            table.add_column(t("field_id"), style="dim")
            table.add_column(t("field_target"))
            table.add_column(t("field_offer"))
            table.add_column(t("field_request"))
            table.add_column(t("field_status"))
            for tr in trades:
                table.add_row(tr.id, tr.target_spark_id,
                              str(len(tr.offer_knowledge_ids)),
                              str(len(tr.request_knowledge_ids)),
                              tr.status)
            console.print(table)

        elif sub in ("history", "历史"):
            history = trade.get_trade_history()
            if not history:
                console.print(f"[dim]{t('no_trade_history')}[/]")
                return
            for h in history:
                console.print(f"  {h['trade_id']}: {h['proposer']} ↔ {h['target']} | received: {h['received']}")

        else:
            console.print(f"[yellow]Unknown trade command: {sub}[/]")
            console.print(f"\n[dim]{t('trade_usage')}[/]")
            return

    def _handle_experience(self, args: list[str]):
        lang = get_language()
        exp = self.engine.experience

        if not args:
            stats = exp.get_stats()
            table = Table(title=t("title_experience"))
            table.add_column("Metric", style="cyan")
            table.add_column("Value")
            table.add_row("Total Experiences", str(stats["total_experiences"]))
            table.add_row("Patterns Detected", str(stats["patterns_detected"]))
            table.add_row("Knowledge Promoted", str(stats["knowledge_promoted"]))
            console.print(table)

            patterns = exp.get_patterns()
            if patterns:
                ptable = Table(title=t("title_patterns"))
                ptable.add_column("Event")
                ptable.add_column("Count", justify="right")
                ptable.add_column("Promoted")
                for p in patterns[:10]:
                    ptable.add_row(
                        p["event"],
                        str(p["count"]),
                        "✅" if p["promoted"] else "—",
                    )
                console.print(ptable)

            console.print(f"\n[dim]{t('exp_usage')}[/]")
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
            if lang == "zh":
                console.print(f"[green]✓ 经验已记录: {entry.id}[/]")
            else:
                console.print(f"[green]✓ Experience logged: {entry.id}[/]")
            return

        if subcmd in ("patterns", "模式"):
            patterns = exp.get_patterns()
            if not patterns:
                if lang == "zh":
                    console.print("[dim]暂无检测到模式（需要同一事件出现2次以上）[/]")
                else:
                    console.print("[dim]No patterns detected yet (need 2+ occurrences of same event)[/]")
                return
            ptable = Table(title="🔄 Patterns")
            ptable.add_column("Event")
            ptable.add_column("Count", justify="right")
            ptable.add_column("Promoted")
            for p in patterns:
                ptable.add_row(
                    p["event"],
                    str(p["count"]),
                    f"✅ → {p['knowledge_id']}" if p["promoted"] else "—",
                )
            console.print(ptable)
            return

        if subcmd in ("recent", "最近"):
            entries = exp.get_recent(10)
            if not entries:
                if lang == "zh":
                    console.print("[dim]暂无经验记录[/]")
                else:
                    console.print("[dim]No experiences recorded yet[/]")
                return
            for e in entries:
                status = "✅" if e.related_knowledge_id else "  "
                console.print(f"  {status} [{e.id}] {e.event} → {e.outcome}")
            return

        if lang == "zh":
            console.print("[dim]用法: 经验 | 经验 log <事件> <结果> | 经验 patterns | 经验 recent[/]")
        else:
            console.print("[dim]Usage: exp | exp log <event> <outcome> | exp patterns | exp recent[/]")

    def _handle_skf(self, args: list[str]):
        lang = get_language()
        from allspark.skf_manager import export_skf, import_skf, SKFPackage

        if not args:
            if lang == "zh":
                console.print("[bold]📦 SKF 知识包管理[/]")
                console.print("[dim]用法:[/]")
                console.print("  skf export <路径>           — 导出知识包")
                console.print("  skf import <路径>           — 导入知识包")
                console.print("  skf info <路径>             — 查看知识包信息")
                console.print("  skf export <路径> --cat <类> — 按分类导出")
            else:
                console.print("[bold]📦 SKF Knowledge Package Manager[/]")
                console.print("[dim]Usage:[/]")
                console.print("  skf export <path>           — Export knowledge package")
                console.print("  skf import <path>           — Import knowledge package")
                console.print("  skf info <path>             — View package info")
                console.print("  skf export <path> --cat <c> — Export by category")
            return

        subcmd = args[0].lower()

        if subcmd in ("export", "导出") and len(args) > 1:
            path = args[1]
            category = ""
            language = ""
            i = 2
            while i < len(args):
                if args[i] in ("--cat", "-c") and i + 1 < len(args):
                    category = args[i + 1]
                    i += 2
                elif args[i] in ("--lang", "-l") and i + 1 < len(args):
                    language = args[i + 1]
                    i += 2
                else:
                    i += 1

            try:
                result = export_skf(self.db, path, category=category, language=language)
                if lang == "zh":
                    console.print(f"[green]✓ 知识包已导出: {result}[/]")
                else:
                    console.print(f"[green]✓ Knowledge package exported: {result}[/]")
            except Exception as e:
                console.print(f"[red]Export failed: {e}[/]")
            return

        if subcmd in ("import", "导入") and len(args) > 1:
            path = args[1]
            try:
                result = import_skf(self.db, path)
                if result["status"] == "ok":
                    imp = result["imported"]
                    if lang == "zh":
                        console.print(f"[green]✓ 知识包导入成功[/]")
                        console.print(f"  知识条目: {imp['knowledge']} 条")
                        console.print(f"  经验记录: {imp['experience']} 条")
                        console.print(f"  本地数据: {imp['local_data']} 条")
                        console.print(f"  跳过(重复): {imp['skipped']} 条")
                        console.print(f"  来源: {result['source_spark']}")
                    else:
                        console.print(f"[green]✓ Knowledge package imported[/]")
                        console.print(f"  Knowledge: {imp['knowledge']} entries")
                        console.print(f"  Experience: {imp['experience']} entries")
                        console.print(f"  Local data: {imp['local_data']} entries")
                        console.print(f"  Skipped (duplicate): {imp['skipped']} entries")
                        console.print(f"  Source: {result['source_spark']}")
                elif result["status"] == "validation_error":
                    if lang == "zh":
                        console.print(f"[red]✗ 知识包验证失败:[/]")
                    else:
                        console.print(f"[red]✗ Package validation failed:[/]")
                    for err in result["errors"]:
                        console.print(f"  [red]• {err}[/]")
            except Exception as e:
                console.print(f"[red]Import failed: {e}[/]")
            return

        if subcmd in ("info", "信息") and len(args) > 1:
            path = args[1]
            try:
                pkg = SKFPackage.import_from_file(path)
                stats = pkg.get_stats()
                table = Table(title="📦 SKF Package Info")
                table.add_column("Field", style="cyan")
                table.add_column("Value")
                table.add_row("AllSpark ID", stats["spark_id"])
                table.add_row("Created", stats["created"])
                table.add_row("Version", stats["version"])
                table.add_row("Knowledge", str(stats["knowledge_count"]))
                table.add_row("Experience", str(stats["experience_count"]))
                table.add_row("Local Data", str(stats["local_data_count"]))
                if stats["categories"]:
                    table.add_row("Categories", ", ".join(f"{k}({v})" for k, v in stats["categories"].items()))
                console.print(table)

                errors = pkg.validate()
                if errors:
                    if lang == "zh":
                        console.print("[yellow]⚠ 验证警告:[/]")
                    else:
                        console.print("[yellow]⚠ Validation warnings:[/]")
                    for err in errors:
                        console.print(f"  [yellow]• {err}[/]")
                else:
                    if lang == "zh":
                        console.print("[green]✓ 知识包格式验证通过[/]")
                    else:
                        console.print("[green]✓ Package format validation passed[/]")
            except Exception as e:
                console.print(f"[red]Failed to read package: {e}[/]")
            return

        if lang == "zh":
            console.print("[dim]用法: skf | skf export <路径> | skf import <路径> | skf info <路径>[/]")
        else:
            console.print("[dim]Usage: skf | skf export <path> | skf import <path> | skf info <path>[/]")

    def _handle_verify(self, args: list[str]):
        lang = get_language()
        from allspark.knowledge_verifier import KnowledgeVerifier, VerificationLevel

        verifier = KnowledgeVerifier(self.db, self.engine.llm if self.engine else None)

        if not args:
            if lang == "zh":
                console.print("[bold]🔍 知识验证系统[/]")
                console.print("[dim]用法:[/]")
                console.print("  verify <知识ID>        — 验证指定知识条目")
                console.print("  verify all             — 验证所有知识")
                console.print("  verify unverified      — 验证未验证的知识")
                console.print("  verify stats           — 查看验证统计")
            else:
                console.print("[bold]🔍 Knowledge Verification System[/]")
                console.print("[dim]Usage:[/]")
                console.print("  verify <knowledge_id>  — Verify specific entry")
                console.print("  verify all             — Verify all knowledge")
                console.print("  verify unverified      — Verify unverified entries")
                console.print("  verify stats           — View verification stats")
            return

        subcmd = args[0].lower()

        if subcmd == "stats":
            rows = self.db.conn.execute(
                "SELECT verification, COUNT(*) as cnt FROM knowledge GROUP BY verification"
            ).fetchall()
            table = Table(title=t("title_verification"))
            table.add_column("Level", style="cyan")
            table.add_column("Count", justify="right")
            for r in rows:
                level = r["verification"]
                icon = {"expert_verified": "✅", "cross_ref": "🔍", "field_tested": "🧪",
                        "partially_verified": "⚠️", "unverified": "❓", "conflict": "⛔"}.get(level, "❓")
                table.add_row(f"{icon} {level}", str(r["cnt"]))
            console.print(table)
            return

        if subcmd == "all":
            rows = self.db.conn.execute("SELECT * FROM knowledge").fetchall()
            entries = [self.db._row_to_entry(r) for r in rows]
        elif subcmd == "unverified":
            rows = self.db.conn.execute(
                "SELECT * FROM knowledge WHERE verification='unverified'"
            ).fetchall()
            entries = [self.db._row_to_entry(r) for r in rows]
        else:
            entry = self.db.get_knowledge(subcmd)
            entries = [entry] if entry else []

        if not entries:
            if lang == "zh":
                console.print("[dim]没有找到需要验证的知识条目[/]")
            else:
                console.print("[dim]No knowledge entries found to verify[/]")
            return

        if lang == "zh":
            console.print(f"[bold]正在验证 {len(entries)} 条知识...[/]")
        else:
            console.print(f"[bold]Verifying {len(entries)} entries...[/]")

        reports = verifier.verify_batch(entries)

        verified_count = 0
        conflict_count = 0
        for report in reports:
            icon = {"expert_verified": "✅", "cross_ref": "🔍", "field_tested": "🧪",
                    "partially_verified": "⚠️", "unverified": "❓", "conflict": "⛔"}.get(report.level, "❓")

            if report.level == "conflict":
                conflict_count += 1
            elif report.level != "unverified":
                verified_count += 1

            entry = self.db.get_knowledge(report.entry_id)
            if entry and entry.verification != report.level:
                entry.verification = report.level
                self.db.save_knowledge(entry)

            console.print(f"  {icon} [{report.entry_id}] {report.entry_title[:40]} → {report.level}")
            if report.warnings:
                for w in report.warnings[:2]:
                    console.print(f"     [dim]{w}[/]")

        if lang == "zh":
            console.print(f"\n[green]验证完成: {verified_count} 条已验证, {conflict_count} 条冲突[/]")
        else:
            console.print(f"\n[green]Verification complete: {verified_count} verified, {conflict_count} conflicts[/]")

    def _handle_network(self, args: list[str]):
        lang = get_language()
        from allspark.spark_network import SparkNetwork

        net = self._lazy_init('_network', lambda: SparkNetwork(db=self.db, llm_engine=self.engine.llm if self.engine else None))

        if not args:
            status = net.get_status()
            table = Table(title=t("title_network"))
            table.add_column("Field", style="cyan")
            table.add_column("Value")
            table.add_row("AllSpark ID", status["spark_id"])
            table.add_row("Discovery", "🟢 Running" if status["running"] else "🔴 Stopped")
            for ch, avail in status["channels"].items():
                table.add_row(ch, "✅" if avail else "❌")
            table.add_row("Known Nodes", str(status["known_nodes"]))
            console.print(table)

            if status["nodes"]:
                ntable = Table(title=t("known_nodes"))
                ntable.add_column("Name")
                ntable.add_column("Knowledge", justify="right")
                ntable.add_column("Status")
                for n in status["nodes"]:
                    ntable.add_row(n["display_name"], str(n["knowledge_count"]), n["status"])
                console.print(ntable)

            if lang == "zh":
                console.print("\n[dim]用法: 网络 | 网络 scan | 网络 start | 网络 stop | 网络 send <节点> <知识ID>[/]")
            else:
                console.print("\n[dim]Usage: net | net scan | net start | net stop | net send <node> <knowledge_id>[/]")
            return

        subcmd = args[0].lower()

        if subcmd in ("scan", "扫描", "detect", "检测"):
            with console.status(t("scanning_channels")):
                channels = net.detect_channels()
            table = Table(title=t("title_channel"))
            table.add_column("Channel", style="cyan")
            table.add_column("Available")
            table.add_column("Details")
            for ch, info in channels.items():
                avail = info.get("available", False)
                detail = ""
                if ch == "lan" and avail:
                    detail = f"IP: {info.get('ip', '')}"
                table.add_row(ch, "✅" if avail else "❌", detail)
            console.print(table)
            return

        if subcmd in ("start", "启动"):
            result = net.start_discovery()
            if result["status"] == "started":
                net.start_exchange_server()
                if lang == "zh":
                    console.print(f"[green]✓ 火种发现服务已启动 (ID: {result['spark_id']})[/]")
                    console.print("[dim]正在广播信标并监听其他火种...[/]")
                else:
                    console.print(f"[green]✓ Discovery started (ID: {result['spark_id']})[/]")
                    console.print("[dim]Broadcasting beacon and listening for other sparks...[/]")
            else:
                console.print(f"[yellow]{result.get('message', result['status'])}[/]")
            return

        if subcmd in ("stop", "停止"):
            result = net.stop_discovery()
            if lang == "zh":
                console.print(f"[green]✓ 火种发现服务已停止 (发现 {result['nodes_found']} 个节点)[/]")
            else:
                console.print(f"[green]✓ Discovery stopped (found {result['nodes_found']} nodes)[/]")
            return

        if subcmd in ("send", "发送") and len(args) > 2:
            node_id = args[1]
            entry_ids = args[2:]
            result = net.send_knowledge(node_id, entry_ids)
            if result["status"] == "ok":
                if lang == "zh":
                    console.print(f"[green]✓ 已发送 {result['sent_count']} 条知识 (对方接受 {result.get('accepted_count', '?')} 条)[/]")
                else:
                    console.print(f"[green]✓ Sent {result['sent_count']} entries (accepted {result.get('accepted_count', '?')})[/]")
            else:
                console.print(f"[red]{result.get('message', 'Send failed')}[/]")
            return

        if subcmd in ("exchange", "交换") and len(args) > 1:
            node_id = args[1]
            result = net.request_exchange(node_id)
            if result["status"] == "ok":
                remote = result.get("remote_index", {})
                comp = result.get("complementary", [])
                if lang == "zh":
                    console.print(f"[green]✓ 握手成功[/]")
                    console.print(f"  对方知识库: {remote.get('total', 0)} 条")
                    if comp:
                        console.print(f"  互补分类: {', '.join(comp)}")
                else:
                    console.print(f"[green]✓ Handshake successful[/]")
                    console.print(f"  Remote knowledge: {remote.get('total', 0)} entries")
                    if comp:
                        console.print(f"  Complementary: {', '.join(comp)}")
            else:
                console.print(f"[red]{result.get('message', 'Exchange failed')}[/]")
            return

        if lang == "zh":
            console.print("[dim]用法: 网络 | 网络 scan | 网络 start | 网络 stop | 网络 send <节点> <ID>[/]")
        else:
            console.print("[dim]Usage: net | net scan | net start | net stop | net send <node> <ID>[/]")

    def _handle_vision(self, args: list[str]):
        lang = get_language()
        from allspark.vision_engine import VisionEngine, VisionTask

        vision = self._lazy_init('_vision', lambda: VisionEngine(llm_engine=self.engine.llm if self.engine else None, db=self.db))

        if not args:
            status = vision.get_status()
            table = Table(title=t("title_vision"))
            table.add_column("Field", style="cyan")
            table.add_column("Value")
            table.add_row("Available", "✅" if status["available"] else "❌")
            table.add_row("Multimodal", "✅" if status["multimodal"] else "❌ (text-only fallback)")
            table.add_row("LLM Model", status.get("llm_model") or "Not loaded")
            console.print(table)

            if lang == "zh":
                console.print("\n[dim]用法:[/]")
                console.print("  识别 <图片路径>              — 通用识别")
                console.print("  识别 plant <图片路径>        — 植物识别")
                console.print("  识别 wound <图片路径>        — 伤口评估")
                console.print("  识别 hazard <图片路径>       — 危险检测")
                console.print("  识别 shelter <图片路径>      — 庇护所评估")
                console.print("  识别 water <图片路径>        — 水源评估")
            else:
                console.print("\n[dim]Usage:[/]")
                console.print("  vision <image_path>              — General analysis")
                console.print("  vision plant <image_path>        — Plant identification")
                console.print("  vision wound <image_path>        — Wound assessment")
                console.print("  vision hazard <image_path>       — Hazard detection")
                console.print("  vision shelter <image_path>      — Shelter evaluation")
                console.print("  vision water <image_path>        — Water source assessment")
            return

        task_map = {
            "plant": VisionTask.PLANT_IDENTIFY,
            "wound": VisionTask.WOUND_ASSESS,
            "hazard": VisionTask.HAZARD_DETECT,
            "shelter": VisionTask.SHELTER_EVAL,
            "water": VisionTask.WATER_SOURCE,
            "tool": VisionTask.TOOL_IDENTIFY,
        }

        if args[0].lower() in task_map and len(args) > 1:
            task = task_map[args[0].lower()]
            image_path = " ".join(args[1:])
        else:
            task = VisionTask.GENERAL
            image_path = " ".join(args)

        if not vision.available:
            console.print(f"[red]{t('vision_not_available')}[/]")
            return

        with console.status(t("analyzing_image")):
            result = vision.analyze_image(image_path, task)

        table = Table(title=f"👁 Analysis: {task.value}")
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        table.add_row("Description", result.description)
        table.add_row("Confidence", result.confidence)
        if result.warnings:
            table.add_row("Warnings", "\n".join(f"⚠ {w}" for w in result.warnings))
        if result.recommendations:
            table.add_row("Recommendations", "\n".join(f"→ {r}" for r in result.recommendations))
        if result.related_knowledge:
            table.add_row("Related Knowledge", ", ".join(result.related_knowledge))
        console.print(table)

    def _handle_power(self, args: list[str]):
        lang = get_language()
        from allspark.power_monitor import PowerMonitor

        pm = self._lazy_init('_power_monitor', lambda: PowerMonitor(db=self.db))

        if not args:
            status = pm.get_status()
            reading = pm.get_current_reading()
            table = Table(title=t("power_monitor"))
            table.add_column(t("field_item"), style="cyan")
            table.add_column(t("field_value"))
            table.add_row("Monitoring", "✅ Active" if status["monitoring"] else "❌ Stopped")
            table.add_row("GPIO", "✅" if status["gpio_available"] else "❌")
            table.add_row("Voltage", f"{reading.voltage_v}V")
            table.add_row("Current", f"{reading.current_a}A")
            table.add_row("Power", f"{reading.power_w}W")
            table.add_row("Energy", f"{reading.energy_wh}Wh")
            table.add_row("Battery", f"{reading.battery_percent}%")
            table.add_row("Charging", "✅" if reading.charging else "❌")
            table.add_row("Source", reading.source)
            console.print(table)

            if reading.source == "no_data":
                console.print(f"[dim]{t('power_no_data')}[/]")
            elif reading.source == "from_db":
                console.print(f"[dim]{t('power_from_db')}[/]")

            runtime = pm.estimate_runtime()
            if "estimated_hours" in runtime:
                console.print(f"\n[dim]{t('est_runtime', hours=runtime['estimated_hours'], mode=runtime.get('mode_recommendation', '?'))}[/]")

            if lang == "zh":
                console.print("\n[dim]用法:[/]")
                console.print("  电力 status           — 当前状态")
                console.print("  电力 start [间隔秒]   — 开始监控")
                console.print("  电力 stop             — 停止监控")
                console.print("  电力 input <Wh> [充电] — 手动输入")
                console.print("  电力 source add <名> <类型> — 注册电源")
                console.print("  电力 history           — 历史记录")
            else:
                console.print("\n[dim]Usage:[/]")
                console.print("  power status           — Current status")
                console.print("  power start [interval] — Start monitoring")
                console.print("  power stop             — Stop monitoring")
                console.print("  power input <Wh> [charging] — Manual input")
                console.print("  power source add <name> <type> — Register source")
                console.print("  power history          — History")
            return

        sub = args[0].lower()

        if sub in ("start", "开始"):
            interval = int(args[1]) if len(args) > 1 else 60
            result = pm.start_monitoring(interval)
            console.print(f"[green]✅ Power monitoring started (interval={interval}s)[/]")
        elif sub in ("stop", "停止"):
            pm.stop_monitoring()
            console.print("[yellow]Power monitoring stopped[/]")
        elif sub in ("input", "手动", "输入"):
            wh = float(args[1]) if len(args) > 1 else 0
            charging = len(args) > 2 and args[2].lower() in ("true", "yes", "1", "charging", "充电")
            result = pm.manual_input(wh, charging)
            console.print(f"[green]✅ Updated: {wh}Wh battery={result['reading']['battery_percent']}%[/]")
        elif sub in ("source", "电源"):
            if len(args) >= 4 and args[1].lower() in ("add", "添加"):
                pm.register_source(args[2], args[3])
                console.print(f"[green]✅ Source registered: {args[2]} ({args[3]})[/]")
            else:
                sources = pm.get_sources()
                if sources:
                    for s in sources:
                        icon = "🟢" if s.available else "🔴"
                        console.print(f"  {icon} {s.name} ({s.type}): {s.power_w}W")
                else:
                    console.print("[dim]No power sources registered[/]")
        elif sub in ("history", "历史"):
            history = pm.get_history(20)
            if history:
                for h in history[-10:]:
                    console.print(f"  {h['timestamp'][:19]}: {h['energy_wh']}Wh {h['battery_percent']}%")
            else:
                console.print("[dim]No history[/]")
        else:
            console.print(f"[yellow]Unknown power command: {sub}[/]")

    def _handle_sensor(self, args: list[str]):
        lang = get_language()
        from allspark.sensor_hub import SensorHub, SensorType

        hub = self._lazy_init('_sensor_hub', lambda: SensorHub(db=self.db))

        if not args:
            status = hub.get_status()
            snap = hub.get_snapshot()
            table = Table(title=t("sensor_hub"))
            table.add_column(t("field_item"), style="cyan")
            table.add_column(t("field_value"))
            table.add_row("Polling", "✅ Active" if status["polling"] else "❌ Stopped")
            table.add_row("I2C", "✅" if status["i2c_available"] else "❌")
            table.add_row("GPIO", "✅" if status["gpio_available"] else "❌")
            table.add_row("Devices", str(status["devices_registered"]))
            if snap.temperature_c is not None:
                table.add_row(t("temperature"), f"{snap.temperature_c}°C")
            if snap.humidity_pct is not None:
                table.add_row(t("humidity"), f"{snap.humidity_pct}%")
            if snap.pressure_hpa is not None:
                table.add_row(t("pressure"), f"{snap.pressure_hpa}hPa")
            if snap.light_lux is not None:
                table.add_row(t("light"), f"{snap.light_lux}lux")
            console.print(table)

            if status["devices_registered"] == 0:
                console.print(f"[dim]{t('sensor_no_devices')}[/]")

            if lang == "zh":
                console.print("\n[dim]用法:[/]")
                console.print("  传感器 list              — 设备列表")
                console.print("  传感器 add <名> <类型>   — 注册设备")
                console.print("  传感器 start             — 开始轮询")
                console.print("  传感器 stop              — 停止轮询")
                console.print("  传感器 input <名> <值>   — 手动输入")
                console.print("  传感器 detect            — 自动检测")
                console.print("  传感器 snapshot           — 环境快照")
            else:
                console.print("\n[dim]Usage:[/]")
                console.print("  sensor list              — Device list")
                console.print("  sensor add <name> <type> — Register device")
                console.print("  sensor start             — Start polling")
                console.print("  sensor stop              — Stop polling")
                console.print("  sensor input <name> <value> — Manual input")
                console.print("  sensor detect            — Auto-detect")
                console.print("  sensor snapshot          — Environment snapshot")
            return

        sub = args[0].lower()

        if sub in ("list", "列表", "ls"):
            devices = hub.get_all_devices()
            if not devices:
                console.print("[dim]No sensors registered[/]")
                return
            table = Table(title=t("sensor_devices"))
            table.add_column(t("sensor_name"), style="cyan")
            table.add_column(t("sensor_type"))
            table.add_column(t("sensor_interface"))
            table.add_column(t("sensor_last_value"))
            for d in devices:
                val = f"{d['last_value']} {d['last_unit']}" if d['last_value'] is not None else "-"
                table.add_row(d["name"], d["type"], d["interface"], val)
            console.print(table)
        elif sub in ("add", "添加"):
            name = args[1] if len(args) > 1 else "sensor"
            stype = args[2] if len(args) > 2 else "temperature"
            hub.register_device(name, stype)
            console.print(f"[green]✅ Sensor registered: {name} ({stype})[/]")
        elif sub in ("start", "开始"):
            hub.start_polling()
            console.print("[green]✅ Sensor polling started[/]")
        elif sub in ("stop", "停止"):
            hub.stop_polling()
            console.print("[yellow]Sensor polling stopped[/]")
        elif sub in ("input", "手动"):
            name = args[1] if len(args) > 1 else ""
            value = float(args[2]) if len(args) > 2 else 0
            reading = hub.manual_input(name, value)
            if reading:
                console.print(f"[green]✅ {name}: {reading.value}{reading.unit}[/]")
            else:
                console.print(f"[red]Device {name} not found[/]")
        elif sub in ("detect", "检测"):
            detected = hub.auto_detect()
            console.print(f"[cyan]Auto-detect found {len(detected)} device(s):[/]")
            for d in detected:
                console.print(f"  📡 {d['name']} ({d['type']}) via {d['interface']} @ {d['address']}")
        elif sub in ("snapshot", "快照", "env"):
            snap = hub.get_snapshot()
            table = Table(title=t("env_snapshot"))
            table.add_column(t("field_metric"), style="cyan")
            table.add_column(t("field_value"))
            if snap.temperature_c is not None:
                table.add_row(t("temperature"), f"{snap.temperature_c}°C")
            if snap.humidity_pct is not None:
                table.add_row(t("humidity"), f"{snap.humidity_pct}%")
            if snap.pressure_hpa is not None:
                table.add_row(t("pressure"), f"{snap.pressure_hpa}hPa")
            if snap.latitude is not None:
                table.add_row("GPS", f"{snap.latitude}, {snap.longitude}")
            if snap.light_lux is not None:
                table.add_row(t("light"), f"{snap.light_lux}lux")
            if snap.air_quality_ppm is not None:
                table.add_row(t("air_quality"), f"{snap.air_quality_ppm}ppm")
            console.print(table)
        else:
            console.print(f"[yellow]Unknown sensor command: {sub}[/]")

    def _handle_preserve(self, args: list[str]):
        lang = get_language()
        from allspark.data_preservation import DataPreservation

        dp = self._lazy_init('_preservation', lambda: DataPreservation(db=self.db))

        if not args:
            status = dp.get_status()
            table = Table(title=t("data_preservation"))
            table.add_column(t("field_item"), style="cyan")
            table.add_column(t("field_value"))
            table.add_row("Auto-Save", "✅ Active" if status["auto_save_running"] else "❌ Stopped")
            table.add_row("Interval", f"{status['auto_save_interval_s']}s")
            table.add_row("Last Save", status.get("last_save_time") or "Never")
            table.add_row("Total Saves", str(status["total_saves"]))
            table.add_row("DB Size", f"{status['db_size_mb']}MB")
            table.add_row("Backups", str(status["backup_count"]))
            table.add_row("Snapshots", str(status["snapshot_count"]))
            console.print(table)

            if lang == "zh":
                console.print("\n[dim]用法:[/]")
                console.print("  固化 start [间隔秒]     — 开始自动保存")
                console.print("  固化 stop              — 停止自动保存")
                console.print("  固化 emergency         — 紧急保存")
                console.print("  固化 snapshot [标签]   — 创建快照")
                console.print("  固化 snapshots         — 列出快照")
                console.print("  固化 restore <路径>    — 恢复快照")
            else:
                console.print("\n[dim]Usage:[/]")
                console.print("  preserve start [interval] — Start auto-save")
                console.print("  preserve stop             — Stop auto-save")
                console.print("  preserve emergency        — Emergency save")
                console.print("  preserve snapshot [label] — Create snapshot")
                console.print("  preserve snapshots        — List snapshots")
                console.print("  preserve restore <path>   — Restore snapshot")
            return

        sub = args[0].lower()

        if sub in ("start", "开始"):
            interval = int(args[1]) if len(args) > 1 else 300
            dp.start_auto_save(interval)
            console.print(f"[green]✅ Auto-save started (interval={interval}s)[/]")
        elif sub in ("stop", "停止"):
            dp.stop_auto_save()
            console.print("[yellow]Auto-save stopped, final save completed[/]")
        elif sub in ("emergency", "紧急"):
            result = dp.emergency_save("manual")
            if result.get("status") == "ok":
                console.print(f"[green]✅ Emergency save: {result.get('path', '')}[/]")
            else:
                console.print(f"[red]❌ Emergency save failed: {result.get('message', '')}[/]")
        elif sub in ("snapshot", "快照"):
            label = args[1] if len(args) > 1 else ""
            result = dp.create_snapshot(label)
            if result.get("status") == "ok":
                console.print(f"[green]✅ Snapshot created: {result['meta']['label'] or 'unnamed'} ({result['meta']['db_size_mb']}MB)[/]")
            else:
                console.print(f"[red]❌ Snapshot failed: {result.get('message', '')}[/]")
        elif sub in ("snapshots", "快照列表"):
            snapshots = dp.list_snapshots()
            if not snapshots:
                console.print("[dim]No snapshots[/]")
            else:
                for s in snapshots:
                    console.print(f"  📦 {s.get('label', 'unnamed')} | {s['created']} | {s['db_size_mb']}MB")
        elif sub in ("restore", "恢复"):
            path_or_label = " ".join(args[1:]) if len(args) > 1 else ""
            result = dp.restore_snapshot(path_or_label)
            if result.get("status") == "ok":
                console.print(f"[green]✅ Restored from: {result['restored_from']}[/]")
                console.print("[yellow]⚠ Restart AllSpark to use restored data[/]")
            else:
                console.print(f"[red]❌ Restore failed: {result.get('message', '')}[/]")
        else:
            console.print(f"[yellow]Unknown preserve command: {sub}[/]")

    def _handle_goal(self, args: list[str]):
        if not hasattr(self.engine, 'goal_engine'):
            console.print("[yellow]Goal engine not loaded[/]")
            return

        ge = self.engine.goal_engine

        if not args:
            summary = ge.get_goal_summary()
            console.print(summary)
            return

        sub = args[0].lower()

        if sub in ("添加", "add", "新建", "new"):
            title = " ".join(args[1:]) if len(args) > 1 else ""
            if not title:
                console.print("[yellow]Please specify a goal title[/]")
                return
            goal = ge.add_manual_goal(title=title)
            console.print(t("goal_added", title=goal.title))
            if goal.milestone_count > 0:
                milestones = self.db.get_milestones_by_goal(goal.id)
                for ms in milestones:
                    status_icon = "✅" if ms.done else "⬜"
                    console.print(f"  {status_icon} {ms.order}. {ms.description}")

        elif sub in ("完成", "complete", "done"):
            goal_id = args[1] if len(args) > 1 else ""
            if not goal_id:
                console.print("[yellow]Please specify a goal ID[/]")
                return
            result = ge.complete_goal(goal_id)
            if result:
                goal = self.db.get_goal(goal_id)
                console.print(t("goal_completed", title=goal.title if goal else goal_id))
            else:
                console.print(t("goal_not_found", id=goal_id))

        elif sub in ("放弃", "abandon", "取消"):
            goal_id = args[1] if len(args) > 1 else ""
            if not goal_id:
                console.print("[yellow]Please specify a goal ID[/]")
                return
            result = ge.abandon_goal(goal_id)
            if result:
                goal = self.db.get_goal(goal_id)
                console.print(t("goal_abandoned", title=goal.title if goal else goal_id))
            else:
                goal = self.db.get_goal(goal_id)
                if goal and goal.priority == "critical":
                    console.print(t("goal_cannot_abandon_critical"))
                else:
                    console.print(t("goal_not_found", id=goal_id))

        elif sub in ("暂停", "pause"):
            goal_id = args[1] if len(args) > 1 else ""
            if not goal_id:
                console.print("[yellow]Please specify a goal ID[/]")
                return
            result = ge.pause_goal(goal_id)
            if result:
                goal = self.db.get_goal(goal_id)
                console.print(t("goal_paused", title=goal.title if goal else goal_id))
            else:
                goal = self.db.get_goal(goal_id)
                if goal and goal.priority == "critical":
                    console.print(t("goal_cannot_pause_critical"))
                else:
                    console.print(t("goal_not_found", id=goal_id))

        elif sub in ("恢复", "resume"):
            goal_id = args[1] if len(args) > 1 else ""
            if not goal_id:
                console.print("[yellow]Please specify a goal ID[/]")
                return
            result = ge.resume_goal(goal_id)
            if result:
                goal = self.db.get_goal(goal_id)
                console.print(t("goal_resumed", title=goal.title if goal else goal_id))
            else:
                console.print(t("goal_not_found", id=goal_id))

        elif sub in ("里程碑", "milestones", "ms"):
            goal_id = args[1] if len(args) > 1 else ""
            if not goal_id:
                console.print("[yellow]Please specify a goal ID[/]")
                return
            detail = ge.get_goal_detail(goal_id)
            if not detail:
                console.print(t("goal_not_found", id=goal_id))
                return
            goal = detail["goal"]
            console.print(f"[bold]{goal.title}[/] — {goal.description}")
            for ms in detail["milestones"]:
                status_icon = "✅" if ms.done else "⬜"
                console.print(f"  {status_icon} {ms.order}. {ms.description}")
            progress_pct = int(goal.progress * 100)
            console.print(f"\n  进度：{progress_pct}% ({goal.milestone_done}/{goal.milestone_count})")

        elif sub in ("自动生成", "auto", "generate"):
            generated = ge.auto_generate_goals()
            if generated:
                console.print(f"[green]✓ Generated {len(generated)} goal(s):[/]")
                for g in generated:
                    console.print(f"  🔴 {g.title}" if g.priority == "critical" else f"  🟡 {g.title}")
            else:
                console.print("[dim]No new goals to generate[/]")

        else:
            console.print(t("goal_usage"))

    def _handle_reset(self, args: list[str]):
        if not hasattr(self.engine, 'reset_manager'):
            console.print("[yellow]Reset manager not loaded[/]")
            return

        rm = self.engine.reset_manager

        if not args:
            console.print(t("reset_usage"))
            return

        sub = args[0].lower()

        if sub in ("状态", "status"):
            status = rm.get_reset_status()
            table = Table(title="🔄 Reset Status")
            table.add_column("Field", style="cyan")
            table.add_column("Value")
            table.add_row("Last Reset", str(status.get("last_reset", "Never")))
            table.add_row("Cooldown", f"{status['cooldown_hours']}h")
            table.add_row("Can Reset", "✅ Yes" if status["can_reset"] else "❌ No (cooldown)")
            console.print(table)

        elif sub in ("评估", "assessment", "l1"):
            from allspark.models import ResetLevel
            evaluation = rm.evaluate_reset(ResetLevel.ASSESSMENT)
            self._print_reset_evaluation(evaluation)
            if evaluation["allowed"]:
                confirm = console.input("[bold red]Confirm L1 reset? (yes/no): [/]").strip().lower()
                if confirm in ("yes", "是", "y"):
                    result = rm.execute_reset(ResetLevel.ASSESSMENT)
                    if result["status"] == "ok":
                        console.print(t("reset_executed", level="L1"))
                    else:
                        console.print(t("reset_rejected", reason=result.get("reason", "")))

        elif sub in ("档案", "archive", "l2"):
            from allspark.models import ResetLevel
            evaluation = rm.evaluate_reset(ResetLevel.ARCHIVE)
            self._print_reset_evaluation(evaluation)
            if evaluation["allowed"]:
                confirm = console.input("[bold red]Confirm L2 reset? (yes/no): [/]").strip().lower()
                if confirm in ("yes", "是", "y"):
                    result = rm.execute_reset(ResetLevel.ARCHIVE)
                    if result["status"] == "ok":
                        console.print(t("reset_executed", level="L2"))
                    else:
                        console.print(t("reset_rejected", reason=result.get("reason", "")))

        elif sub in ("出厂", "factory", "l3"):
            from allspark.models import ResetLevel
            evaluation = rm.evaluate_reset(ResetLevel.FACTORY)
            self._print_reset_evaluation(evaluation)
            if evaluation["allowed"]:
                confirm = console.input("[bold red]⚠️ FACTORY RESET - ALL DATA WILL BE LOST! Type 'FACTORY' to confirm: [/]").strip()
                if confirm == "FACTORY":
                    result = rm.execute_reset(ResetLevel.FACTORY, force=True)
                    if result["status"] == "ok":
                        console.print(t("reset_executed", level="L3"))
                        console.print("[bold yellow]⚠️ System requires restart to complete factory reset.[/]")
                        console.print("[dim]All data has been erased. Restart AllSpark to begin setup.[/]")
                        self.running = False
                    else:
                        console.print(t("reset_rejected", reason=result.get("reason", "")))
                else:
                    console.print("[dim]Factory reset cancelled[/]")

        else:
            console.print(t("reset_usage"))

    def _print_reset_evaluation(self, evaluation: dict):
        level_name = evaluation.get("level_name", "")
        allowed = evaluation.get("allowed", False)
        description = evaluation.get("description", "")

        console.print(f"\n[bold]Reset Evaluation — {level_name}[/]")
        console.print(f"  Allowed: {'✅' if allowed else '❌'}")
        if description:
            console.print(f"  Description: {description}")
        if evaluation.get("affected_data"):
            console.print("  Affected data:")
            for item in evaluation["affected_data"]:
                console.print(f"    - {item}")
        if evaluation.get("warnings"):
            for w in evaluation["warnings"]:
                console.print(f"  [yellow]⚠ {w}[/]")
        if evaluation.get("backup_recommended"):
            console.print("  [dim]💡 A backup snapshot will be created before reset[/]")

    def _handle_briefing(self):
        if not hasattr(self.engine, 'daily_briefing'):
            console.print("[yellow]Daily briefing module not loaded[/]")
            return
        briefing = self.engine.daily_briefing.generate()
        console.print(Panel(briefing, title="📰 Daily Briefing", border_style="cyan"))

    def _handle_timeline(self, args: list[str]):
        if not hasattr(self.engine, 'timeline'):
            console.print("[yellow]Timeline module not loaded[/]")
            return
        tl = self.engine.timeline

        if not args:
            output = tl.format_timeline()
            console.print(output)
            return

        sub = args[0].lower()
        if sub in ("天", "day") and len(args) > 1:
            try:
                day = int(args[1])
                summary = tl.get_day_summary(day)
                if summary["event_count"] == 0:
                    console.print(f"[dim]No events on day {day}[/]")
                else:
                    console.print(tl.format_timeline(summary["events"]))
            except ValueError:
                console.print("[yellow]Invalid day number[/]")
        elif sub in ("添加", "add"):
            title = " ".join(args[1:]) if len(args) > 1 else ""
            if not title:
                console.print("[yellow]Please specify an event title[/]")
                return
            tl.add_event("system_event", title, description="Manual entry")
            console.print(f"[green]✓ Event added: {title}[/]")
        else:
            console.print("[dim]Usage: timeline | timeline day <N> | timeline add <title>[/]")

    def _handle_diary(self, args: list[str]):
        if not hasattr(self.engine, 'diary'):
            console.print("[yellow]Diary module not loaded[/]")
            return
        dm = self.engine.diary

        if not args:
            output = dm.format_entries()
            console.print(output)
            return

        sub = args[0].lower()

        if sub in ("写", "add", "写日记", "new"):
            console.print("[dim]Enter diary content (type END on a new line to finish):[/]")
            lines = []
            while True:
                try:
                    line = console.input("").strip()
                    if line == "END":
                        break
                    lines.append(line)
                except (EOFError, KeyboardInterrupt):
                    break
            content = "\n".join(lines)
            if not content:
                console.print("[yellow]Empty entry, not saved[/]")
                return
            emotion = "neutral"
            result = dm.add_entry(content=content, emotion=emotion)
            console.print(f"[green]✓ Diary entry saved: {result['id']} ({result['content_length']} chars)[/]")

        elif sub in ("查看", "view", "show"):
            entry_id = args[1] if len(args) > 1 else ""
            if not entry_id:
                entries = dm.get_entries(limit=10)
                console.print(dm.format_entries(entries))
            else:
                entry = dm.get_entry(entry_id)
                if entry:
                    console.print(dm.format_entry_detail(entry))
                else:
                    console.print(f"[yellow]Entry not found: {entry_id}[/]")

        elif sub in ("删除", "delete", "remove"):
            entry_id = args[1] if len(args) > 1 else ""
            if dm.delete_entry(entry_id):
                console.print(f"[green]✓ Entry deleted: {entry_id}[/]")
            else:
                console.print(f"[yellow]Entry not found: {entry_id}[/]")

        elif sub in ("情绪", "emotion", "stats"):
            stats = dm.get_emotion_stats()
            table = Table(title="📝 Diary Stats")
            table.add_column("Metric", style="cyan")
            table.add_column("Value")
            table.add_row("Total Entries", str(stats["total_entries"]))
            table.add_row("Positive", str(stats["positive"]))
            table.add_row("Neutral", str(stats["neutral"]))
            table.add_row("Negative", str(stats["negative"]))
            table.add_row("Positive Ratio", f"{stats['positive_ratio']:.0%}")
            console.print(table)

        else:
            console.print("[dim]Usage: diary | diary add | diary view [ID] | diary delete <ID> | diary stats[/]")

    def _handle_weather(self, args: list[str]):
        if not hasattr(self.engine, 'weather'):
            console.print("[yellow]Weather module not loaded[/]")
            return
        wp = self.engine.weather

        if not args:
            output = wp.format_prediction()
            console.print(Panel(output, title="🌤️ Weather", border_style="cyan"))
            return

        sub = args[0].lower()
        if sub in ("云图", "cloud", "clouds"):
            console.print(wp.get_cloud_guide())
        elif sub in ("气压", "pressure") and len(args) > 1:
            try:
                hpa = float(args[1])
                wp.set_manual_pressure(hpa)
                console.print(f"[green]✓ Pressure set: {hpa} hPa[/]")
            except ValueError:
                console.print("[yellow]Invalid pressure value[/]")
        else:
            console.print("[dim]Usage: weather | weather clouds | weather pressure <hPa>[/]")

    def _handle_psychology(self, args: list[str]):
        if not hasattr(self.engine, 'psychology'):
            console.print("[yellow]Psychology module not loaded[/]")
            return
        pt = self.engine.psychology

        if not args:
            output = pt.format_status()
            console.print(Panel(output, title="🧠 Psychology", border_style="cyan"))
            return

        sub = args[0].lower()
        if sub in ("评估", "assess", "问卷", "quiz"):
            questions = pt.get_self_assessment_questions()
            console.print(f"[bold]{t('psych_assessment_title')}[/]\n")
            answers = {}
            for q in questions:
                console.print(f"  {q['question']}")
                for i, opt in enumerate(q["options"]):
                    console.print(f"    {i+1}. {opt}")
                try:
                    choice = console.input("  → ").strip()
                    idx = int(choice) - 1 if choice.isdigit() else 0
                    idx = max(0, min(idx, len(q["options"]) - 1))
                    answers[q["id"]] = idx
                except (ValueError, EOFError, KeyboardInterrupt):
                    answers[q["id"]] = 0
                console.print("")

            result = pt.process_assessment(answers)
            console.print(f"  {t('psych_score_result', score=result['score'], state=result['state'])}")
            console.print(f"  {t('psych_advice', advice=result['advice'])}")
        else:
            console.print("[dim]Usage: psychology | psychology assess[/]")

    def _handle_gps(self, args: list[str]):
        if not hasattr(self.engine, 'gps_manager'):
            console.print("[yellow]GPS module not loaded[/]")
            return
        gm = self.engine.gps_manager

        if not args:
            output = gm.format_position()
            console.print(output)
            return

        sub = args[0].lower()
        if sub in ("设置", "set") and len(args) >= 3:
            try:
                lat = float(args[1])
                lon = float(args[2])
                alt = float(args[3]) if len(args) > 3 else 0.0
                pos = gm.set_manual_position(lat, lon, alt)
                console.print(f"[green]✓ Position set: {lat:.4f}°, {lon:.4f}°[/]")
            except ValueError:
                console.print("[yellow]Invalid coordinates. Usage: gps set <lat> <lon> [alt][/]")
        elif sub in ("轨迹", "track"):
            output = gm.format_track()
            console.print(output)
        elif sub in ("记录", "record"):
            label = " ".join(args[1:]) if len(args) > 1 else ""
            result = gm.record_track_point(label)
            if result:
                console.print(f"[green]✓ Track point recorded: {result}[/]")
            else:
                console.print("[yellow]No position available. Set position first.[/]")
        elif sub in ("距离", "distance") and len(args) >= 5:
            try:
                lat1, lon1 = float(args[1]), float(args[2])
                lat2, lon2 = float(args[3]), float(args[4])
                dist = gm.calculate_distance(lat1, lon1, lat2, lon2)
                bearing = gm.calculate_bearing(lat1, lon1, lat2, lon2)
                direction = gm.bearing_to_direction(bearing)
                console.print(f"  {t('gps_distance_result', dist=dist, direction=direction, bearing=bearing)}")
            except ValueError:
                console.print("[yellow]Invalid coordinates[/]")
        else:
            console.print("[dim]Usage: gps | gps set <lat> <lon> [alt] | gps track | gps record [label] | gps distance <lat1> <lon1> <lat2> <lon2>[/]")

    def _handle_environment(self):
        if not hasattr(self.engine, 'environment'):
            console.print("[yellow]Environment module not loaded[/]")
            return
        output = self.engine.environment.format_assessment()
        console.print(Panel(output, title="🌍 Environment", border_style="green"))

    def _handle_voice(self, args: list[str]):
        if not hasattr(self.engine, 'voice'):
            console.print("[yellow]Voice module not loaded[/]")
            return
        vm = self.engine.voice

        if not args:
            output = vm.format_status()
            console.print(output)
            return

        sub = args[0].lower()
        if sub in ("加载", "load", "模型"):
            model_name = args[1] if len(args) > 1 else "base"
            console.print(f"[dim]Loading Whisper model '{model_name}'... (first time may download)[/]")
            result = vm.load_whisper(model_name)
            if result["status"] == "ok":
                console.print(f"[green]✓ Whisper model '{model_name}' loaded[/]")
            else:
                console.print(f"[red]✗ {result['message']}[/]")

        elif sub in ("识别", "transcribe", "转写"):
            if len(args) > 1:
                audio_path = args[1]
                result = vm.transcribe(audio_path)
            else:
                console.print("[dim]Recording 5 seconds...[/]")
                result = vm.transcribe_from_mic(duration=5)

            if result.get("status") == "ok":
                console.print(f"[green]Transcribed ({result.get('language', '?')}):[/]")
                console.print(f"  {result['text']}")
            else:
                console.print(f"[red]✗ {result.get('message', 'Unknown error')}[/]")

        elif sub in ("说话", "speak", "朗读"):
            text = " ".join(args[1:]) if len(args) > 1 else t("voice_default_text")
            result = vm.speak(text)
            if result["status"] != "ok":
                console.print(f"[red]✗ {result.get('message', '')}[/]")

        elif sub in ("日记", "diary"):
            console.print("[dim]Recording voice diary (10 seconds)...[/]")
            result = vm.voice_diary(duration=10, emotion="neutral")
            if result.get("status") == "ok":
                console.print(f"[green]✓ Voice diary saved:[/]")
                console.print(f"  {result['text']}")
                if result.get("diary_entry"):
                    console.print(f"  Entry ID: {result['diary_entry']['id']}")
            else:
                console.print(f"[red]✗ {result.get('message', '')}[/]")

        else:
            console.print("[dim]Usage: voice | voice load [model] | voice transcribe [file] | voice speak <text> | voice diary[/]")
