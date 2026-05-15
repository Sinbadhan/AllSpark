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
        banner.append("🔥 火 种 / AllSpark\n", style="bold red")
        banner.append(f"离线人工智能生存系统 v{__version__}\n", style="dim")
        banner.append("━━━━━━━━━━━━━━━━━━━━━━━━━━", style="dim")
        banner.append("\n在极端环境下，保存并重建人类文明。", style="italic")
        console.print(Panel(banner, border_style="red", padding=(1, 2)))

    def _print_initial_status(self):
        warnings = self.engine.resource_mgr.check_warnings()
        mode, changed = self.engine.resource_mgr.update_operating_mode()
        mode_names = {
            OperatingMode.PROACTIVE: "主动模式",
            OperatingMode.STANDARD: "标准模式",
            OperatingMode.ECONOMY: "节能模式",
            OperatingMode.HIBERNATION: "休眠模式",
            OperatingMode.RECOVERY: "恢复模式",
        }
        self.engine.personality.determine_mode(
            mode, warnings,
            self.engine.survival.assess()["phase"]
        )
        greeting = self.engine.personality.greet()
        console.print(f"\n{greeting}")
        console.print(f"运行模式：{mode_names.get(mode, mode.value)}")

        if warnings:
            for w in warnings:
                style = "bold red" if w["level"] == "critical" else "yellow"
                console.print(f"[{style}]{w['message']}[/]")

        console.print("\n输入 [bold]'帮助'[/] 查看可用命令。")

    def _process_command(self, user_input: str):
        parts = user_input.split()
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

        response = self.engine.process_input(user_input)
        console.print(response)

    def _handle_status(self):
        assessment = self.engine.survival.assess()
        mode, _ = self.engine.resource_mgr.update_operating_mode()
        warnings = self.engine.resource_mgr.check_warnings()

        mode_names = {
            OperatingMode.PROACTIVE: "主动模式 🟢",
            OperatingMode.STANDARD: "标准模式 🟡",
            OperatingMode.ECONOMY: "节能模式 🟠",
            OperatingMode.HIBERNATION: "休眠模式 🔴",
            OperatingMode.RECOVERY: "恢复模式 🔵",
        }

        phase_desc = assessment["phase_description"]

        status_table = Table(title="🔥 生存评估报告", show_header=True, header_style="bold")
        status_table.add_column("项目", style="cyan")
        status_table.add_column("状态", style="white")
        status_table.add_row("运行模式", mode_names.get(mode, str(mode)))
        status_table.add_row("生存阶段", phase_desc)

        if assessment["bottleneck"]:
            b = assessment["bottleneck"]
            status_table.add_row(
                "🚨 关键瓶颈",
                f"{b['resource']}（剩余 {b['remaining']:.1f}{b['unit']}）",
                style="bold red"
            )

        console.print(status_table)

        if warnings:
            console.print("\n[bold]⚠️ 警告：[/]")
            for w in warnings:
                style = "bold red" if w["level"] == "critical" else "yellow"
                console.print(f"  [{style}]{w['message']}[/]")

        resources = self.engine.resource_mgr.get_all_resources()
        res_table = Table(title="📦 资源清单", show_header=True, header_style="bold")
        res_table.add_column("资源", style="cyan")
        res_table.add_column("当前量", justify="right")
        res_table.add_column("预计可用", justify="right")
        res_table.add_column("状态", justify="center")

        for r in resources:
            if r.type == ResourceType.POWER:
                avail = f"{r.estimated_remaining_hours:.1f}h"
                status = "🟢" if r.estimated_remaining_hours > 72 else "🟡" if r.estimated_remaining_hours > 24 else "🔴"
                res_table.add_row("⚡ 电力", f"{r.current_amount:.0f}Wh", avail, status)
            elif r.type == ResourceType.WATER:
                days = r.estimated_remaining_hours / 24.0
                status = "🟢" if days > 7 else "🟡" if days > 3 else "🔴"
                res_table.add_row("💧 饮水", f"{r.current_amount:.1f}L", f"{days:.1f}天", status)
            elif r.type == ResourceType.FOOD:
                days = r.estimated_remaining_hours / 24.0
                status = "🟢" if days > 14 else "🟡" if days > 5 else "🔴"
                res_table.add_row("🍞 食物", f"{r.current_amount:.0f}kcal", f"{days:.1f}天", status)
            elif r.type == ResourceType.FIRE:
                status = "🟢" if r.current_amount > 20 else "🟡" if r.current_amount > 10 else "🔴"
                res_table.add_row("🔥 火源", f"{r.current_amount:.0f}次", f"{r.current_amount/r.daily_consumption:.0f}天" if r.daily_consumption > 0 else "∞", status)
            elif r.type == ResourceType.STORAGE:
                total = r.daily_consumption
                used = r.daily_intake
                pct = ((total - used) / total * 100) if total > 0 else 0
                status = "🟢" if pct > 30 else "🟡" if pct > 10 else "🔴"
                res_table.add_row("💾 存储", f"{used:.0f}/{total:.0f}GB", f"{pct:.1f}%", status)

        console.print(res_table)
        console.print("[dim]⚠️ 以上数据为估算值，仅供参考。使用 '设置' 命令手动校正。[/dim]")

        tasks = self.engine.planner.get_all_active()
        if tasks:
            task_table = Table(title="📋 活跃任务", show_header=True, header_style="bold")
            task_table.add_column("ID", style="dim")
            task_table.add_column("阶段", justify="center")
            task_table.add_column("任务")
            task_table.add_column("状态", justify="center")
            for t in tasks:
                status_icon = {"pending": "⬜", "in_progress": "🔄", "completed": "✅", "failed": "❌"}.get(t.status, "❓")
                task_table.add_row(t.id, f"Phase {t.phase}", t.title, status_icon)
            console.print(task_table)

    def _handle_resources(self):
        console.print(self.engine.resource_mgr.get_resource_summary())

    def _handle_map(self, args: list[str]):
        if not args:
            console.print(self.engine.maps.format_map())
            return

        subcmd = args[0].lower()

        if subcmd == "add":
            console.print("[bold]添加地点到地图[/]")
            name = console.input("  名称: ").strip()
            if not name:
                console.print("[dim]已取消[/]")
                return
            poi_type = console.input("  类型(water/shelter/food/danger/resource/camp/medical/other): ").strip() or "other"
            desc = console.input("  描述(可选): ").strip()
            dist_str = console.input("  距离(km, 可选): ").strip()
            dist = float(dist_str) if dist_str else 0.0
            direction = console.input("  方向(可选): ").strip()
            notes = console.input("  备注(可选): ").strip()

            poi = self.engine.maps.add_poi(
                name=name, poi_type=poi_type, description=desc,
                distance_km=dist, direction=direction, notes=notes
            )
            console.print(f"[green]✓ 已添加：{poi.name} ({poi.id})[/]")

        elif subcmd == "remove" and len(args) > 1:
            self.engine.maps.remove_poi(args[1])
            console.print(f"[green]✓ 已删除：{args[1]}[/]")

        elif subcmd in ("water", "shelter", "food", "danger", "resource", "camp", "medical"):
            pois = self.engine.maps.get_by_type(subcmd)
            if pois:
                for p in pois:
                    console.print(self.engine.maps.format_poi_detail(p))
                    console.print("")
            else:
                console.print(f"[dim]没有类型为 '{subcmd}' 的地点[/]")

        else:
            console.print("[dim]用法: map | map add | map remove <id> | map <类型>[/]")

    def _handle_set(self, args: list[str]):
        if len(args) < 2:
            console.print("[dim]用法: 设置 <资源类型> <值> [消耗率] [充入率]")
            console.print("资源类型: power/water/food/fire/storage")
            console.print("示例: 设置 power 100 120 50")
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
            console.print(f"[red]未知资源类型：{args[0]}[/]")
            return

        try:
            amount = float(args[1])
            consumption = float(args[2]) if len(args) > 2 else None
            intake = float(args[3]) if len(args) > 3 else None
        except ValueError:
            console.print("[red]数值格式错误[/]")
            return

        self.engine.resource_mgr.update_resource(rtype, amount, consumption, intake)
        updated = self.engine.resource_mgr.get_resource(rtype)
        console.print(f"[green]✓ {rtype.value} 已更新：{updated.current_amount}{updated.unit}[/]")
        console.print(f"  预计可用：{updated.estimated_remaining_hours:.1f}小时")

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
            console.print(f"[green]✓ 任务 {args[1]} 已完成[/]")
        elif subcmd in ("开始", "start") and len(args) > 1:
            self.engine.planner.start_task(args[1])
            console.print(f"[green]✓ 任务 {args[1]} 已开始[/]")
        elif subcmd in ("失败", "fail") and len(args) > 1:
            self.engine.planner.fail_task(args[1])
            console.print(f"[yellow]✓ 任务 {args[1]} 已标记失败[/]")
        else:
            console.print("[dim]用法: 任务 | 任务 完成 <id> | 任务 开始 <id> | 任务 失败 <id>[/]")

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
            table = Table(title=self._t(f"生存价值: {result['member_name']}", f"Survival Value: {result['member_name']}"))
            table.add_column(self._t("维度", "Dimension"), style="cyan")
            table.add_column(self._t("分数", "Score"))
            for dim, val in result["dimensions"].items():
                bar = "█" * int(val * 10) + "░" * (10 - int(val * 10))
                table.add_row(dim, f"{val:.3f} {bar}")
            table.add_row(self._t("[bold]综合[/]", "[bold]Composite[/]"), f"[bold]{result['composite_value']:.3f}[/]")
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
            table = Table(title=self._t(f"交易评估: {tid}", f"Trade Evaluation: {tid}"))
            table.add_column(self._t("项目", "Field"), style="cyan")
            table.add_column(self._t("值", "Value"))
            table.add_row(self._t("评估", "Evaluation"), result["evaluation"])
            table.add_row(self._t("原因", "Reason"), result["reason"])
            table.add_row(self._t("己方价值", "Your Offer Value"), str(result["your_offer_value"]))
            table.add_row(self._t("对方价值", "Their Offer Value"), str(result["their_offer_value"]))
            table.add_row(self._t("新知识数", "New Knowledge"), str(result["new_knowledge_count"]))
            console.print(table)

        elif sub in ("list", "列表", "ls"):
            trades = trade.get_active_trades()
            if not trades:
                console.print(self._t("[green]无活跃交易[/]", "[green]No active trades[/]"))
                return
            table = Table(title=self._t("活跃交易", "Active Trades"))
            table.add_column("ID", style="cyan")
            table.add_column(self._t("目标", "Target"))
            table.add_column(self._t("提供", "Offer"))
            table.add_column(self._t("请求", "Request"))
            table.add_column(self._t("状态", "Status"))
            for t in trades:
                table.add_row(t.id, t.target_spark_id,
                              str(len(t.offer_knowledge_ids)),
                              str(len(t.request_knowledge_ids)),
                              t.status)
            console.print(table)

        elif sub in ("history", "历史"):
            history = trade.get_trade_history()
            if not history:
                console.print(self._t("[dim]无交易历史[/]", "[dim]No trade history[/]"))
                return
            for h in history:
                console.print(f"  {h['trade_id']}: {h['proposer']} ↔ {h['target']} | received: {h['received']}")

        else:
            console.print(f"[yellow]Unknown trade command: {sub}[/]")
            if lang == "zh":
                console.print("\n[dim]用法: llm status | llm chat <消息> | llm load[/]")
            else:
                console.print("\n[dim]Usage: llm status | llm chat <message> | llm load[/]")
            return

        subcmd = args[0].lower()

        if subcmd in ("load", "加载"):
            with console.status(self._t("加载模型中...", "Loading model...")):
                ok = llm.load()
            if ok:
                self.engine.registry.register("llm", llm)
                self.engine.registry.save_to_db(self.db)
                if lang == "zh":
                    console.print(f"[green]✓ 模型 {llm.model_name} 加载成功[/]")
                else:
                    console.print(f"[green]✓ Model {llm.model_name} loaded[/]")
            else:
                console.print(f"[red]{llm.error}[/]")
            return

        if subcmd in ("chat", "问") and len(args) > 1:
            message = " ".join(args[1:])
            if not llm.available:
                console.print(self._t("[red]LLM 不可用，请先用 'llm load' 加载[/]", "[red]LLM not available. Use 'llm load' first.[/]"))
                return
            with console.status(self._t("思考中...", "Thinking...")):
                response = llm.survival_chat(message, phase=self.engine.survival.assess().phase)
            console.print(Panel(response, title="🤖 AllSpark AI"))
            return

        if lang == "zh":
            console.print("[dim]用法: llm | llm load | llm chat <消息>[/]")
        else:
            console.print("[dim]Usage: llm | llm load | llm chat <message>[/]")

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

            if lang == "zh":
                console.print("\n[dim]用法: 经验 | 经验 log <事件> <结果> | 经验 patterns[/]")
            else:
                console.print("\n[dim]Usage: exp | exp log <event> <outcome> | exp patterns[/]")
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
                ntable = Table(title=self._t("已知节点", "Known Nodes"))
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
            with console.status(self._t("扫描通信渠道...", "Scanning channels...")):
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
            if lang == "zh":
                console.print("[red]视觉引擎不可用，需要先加载 LLM 模型 (使用 'llm load')[/]")
            else:
                console.print("[red]Vision engine not available. Load LLM model first ('llm load')[/]")
            return

        with console.status(self._t("分析图像中...", "Analyzing image...")):
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
            table = Table(title=self._t("⚡ 电力监控", "⚡ Power Monitor"))
            table.add_column(self._t("项目", "Field"), style="cyan")
            table.add_column(self._t("值", "Value"))
            table.add_row("Monitoring", "✅ Active" if status["monitoring"] else "❌ Stopped")
            table.add_row("GPIO", "✅" if status["gpio_available"] else "❌ (simulated)")
            table.add_row("Voltage", f"{reading.voltage_v}V")
            table.add_row("Current", f"{reading.current_a}A")
            table.add_row("Power", f"{reading.power_w}W")
            table.add_row("Energy", f"{reading.energy_wh}Wh")
            table.add_row("Battery", f"{reading.battery_percent}%")
            table.add_row("Charging", "✅" if reading.charging else "❌")
            table.add_row("Source", reading.source)
            console.print(table)

            runtime = pm.estimate_runtime()
            if "estimated_hours" in runtime:
                console.print(self._t(f"\n[dim]预计续航: {runtime['estimated_hours']:.1f}h | 推荐模式: {runtime.get('mode_recommendation', '?')}[/]", f"\n[dim]Est. runtime: {runtime['estimated_hours']:.1f}h | Mode: {runtime.get('mode_recommendation', '?')}[/]"))

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
            table = Table(title=self._t("📡 传感器", "📡 Sensor Hub"))
            table.add_column(self._t("项目", "Field"), style="cyan")
            table.add_column(self._t("值", "Value"))
            table.add_row("Polling", "✅ Active" if status["polling"] else "❌ Stopped")
            table.add_row("I2C", "✅" if status["i2c_available"] else "❌")
            table.add_row("GPIO", "✅" if status["gpio_available"] else "❌")
            table.add_row("Devices", str(status["devices_registered"]))
            if snap.temperature_c is not None:
                table.add_row(self._t("温度", "Temperature"), f"{snap.temperature_c}°C")
            if snap.humidity_pct is not None:
                table.add_row(self._t("湿度", "Humidity"), f"{snap.humidity_pct}%")
            if snap.pressure_hpa is not None:
                table.add_row(self._t("气压", "Pressure"), f"{snap.pressure_hpa}hPa")
            if snap.light_lux is not None:
                table.add_row(self._t("光照", "Light"), f"{snap.light_lux}lux")
            console.print(table)

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
            table = Table(title=self._t("传感器设备", "Sensor Devices"))
            table.add_column(self._t("名称", "Name"), style="cyan")
            table.add_column(self._t("类型", "Type"))
            table.add_column(self._t("接口", "Interface"))
            table.add_column(self._t("最新值", "Last Value"))
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
            table = Table(title=self._t("环境快照", "Environment Snapshot"))
            table.add_column(self._t("指标", "Metric"), style="cyan")
            table.add_column(self._t("值", "Value"))
            if snap.temperature_c is not None:
                table.add_row(self._t("温度", "Temperature"), f"{snap.temperature_c}°C")
            if snap.humidity_pct is not None:
                table.add_row(self._t("湿度", "Humidity"), f"{snap.humidity_pct}%")
            if snap.pressure_hpa is not None:
                table.add_row(self._t("气压", "Pressure"), f"{snap.pressure_hpa}hPa")
            if snap.latitude is not None:
                table.add_row("GPS", f"{snap.latitude}, {snap.longitude}")
            if snap.light_lux is not None:
                table.add_row(self._t("光照", "Light"), f"{snap.light_lux}lux")
            if snap.air_quality_ppm is not None:
                table.add_row(self._t("空气质量", "Air Quality"), f"{snap.air_quality_ppm}ppm")
            console.print(table)
        else:
            console.print(f"[yellow]Unknown sensor command: {sub}[/]")

    def _handle_preserve(self, args: list[str]):
        lang = get_language()
        from allspark.data_preservation import DataPreservation

        dp = self._lazy_init('_preservation', lambda: DataPreservation(db=self.db))

        if not args:
            status = dp.get_status()
            table = Table(title=self._t("💾 数据固化", "💾 Data Preservation"))
            table.add_column(self._t("项目", "Field"), style="cyan")
            table.add_column(self._t("值", "Value"))
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
