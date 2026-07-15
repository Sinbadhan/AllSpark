from rich.panel import Panel
from rich.table import Table

from allspark.commands.base import BaseCommand
from allspark.core.i18n import get_language, t


class LLMCommand(BaseCommand):
    COMMAND_NAME = "llm"
    ALIASES = ("ai", "模型")

    def execute(self, args: list[str]) -> None:
        llm = self.container.get("llm")
        if llm is None:
            return
        registry = self.container.require("registry")
        survival = self.container.require("survival_engine")

        if not args:
            status = llm.get_status()
            table = Table(title=t("title_llm_status"))
            table.add_column(t("field_item"), style="cyan")
            table.add_column(t("field_value"))
            table.add_row(t("field_available"), t("llm_available_yes") if status["available"] else t("llm_available_no"))
            table.add_row(t("field_model"), status["model_name"])
            table.add_row(t("field_path"), status.get("model_path") or t("field_not_loaded"))
            if status.get("error"):
                table.add_row(t("field_error"), f"[red]{status['error']}[/]")
            self.console.print(table)
            return

        subcmd = args[0].lower()

        if subcmd in ("load", "加载"):
            with self.console.status(t("llm_loading")):
                ok = llm.load()
            if ok:
                registry.register("llm", llm)
                registry.save_to_db(self.db)
                self.console.print(f"[green]{t('llm_loaded', model=llm.model_name)}[/]")
            else:
                self.console.print(f"[red]{llm.error}[/]")
            return

        if subcmd in ("chat", "问") and len(args) > 1:
            message = " ".join(args[1:])
            if not llm.available:
                self.console.print(f"[red]{t('llm_not_available')}[/]")
                return
            with self.console.status(t("llm_thinking")):
                response = llm.survival_chat(
                    message, phase=survival.assess().get("phase")
                )
            self.console.print(Panel(response, title=t("title_allspark_ai")))
            return

        self.console.print(f"[dim]{t('llm_usage')}[/]")


class ModuleCommand(BaseCommand):
    COMMAND_NAME = "module"
    ALIASES = ("模块", "modules", "mod")

    def execute(self, args: list[str]) -> None:
        registry = self.container.require("registry")
        lang = get_language()

        if not args:
            self.console.print(registry.format_status(lang=lang))
            disabled = registry.get_disabled_by_hardware()
            if disabled:
                self.console.print(f"\n[dim]{t('module_disabled_hw', modules=', '.join(disabled))}[/]")
                self.console.print(f"[dim]{t('module_enable_hint')}[/]")
            return

        subcmd = args[0].lower()

        if subcmd in ("enable", "启用") and len(args) > 1:
            mod_name = args[1]
            if not registry.is_available(mod_name):
                self.console.print(f"[red]{t('module_not_supported', name=mod_name)}[/]")
                return
            registry.enable(mod_name)
            registry.save_to_db(self.db)
            self.console.print(f"[green]{t('module_enabled', name=mod_name)}[/]")

        elif subcmd in ("disable", "禁用") and len(args) > 1:
            mod_name = args[1]
            if registry.is_loaded(mod_name):
                mod_def = registry._modules.get(mod_name)
                if mod_def and mod_def.is_core:
                    self.console.print(f"[red]{t('module_core_no_disable', name=mod_name)}[/]")
                    return
            registry.disable(mod_name)
            registry.save_to_db(self.db)
            self.console.print(f"[green]{t('module_disabled', name=mod_name)}[/]")

        elif subcmd in ("list", "列表", "ls"):
            self.console.print(registry.format_status(lang=lang))

        else:
            self.console.print(f"[dim]{t('module_usage')}[/]")


class SKFCommand(BaseCommand):
    COMMAND_NAME = "skf"
    ALIASES = ("知识包",)

    def execute(self, args: list[str]) -> None:
        from allspark.services.skf_manager import SKFPackage, export_skf, import_skf

        if not args:
            self.console.print(f"[bold]{t('skf_title')}[/]")
            self.console.print(f"[dim]{t('skf_usage')}[/]")
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
                self.console.print(f"[green]✓ {t('skf_exported', result=result)}[/]")
            except Exception as e:
                self.console.print(f"[red]{t('skf_export_failed')}: {e}[/]")
            return

        if subcmd in ("import", "导入") and len(args) > 1:
            path = args[1]
            try:
                imp_result: dict = import_skf(self.db, path)
                if imp_result["status"] == "ok":
                    imp = imp_result["imported"]
                    self.console.print(f"[green]✓ {t('skf_imported')}[/]")
                    self.console.print(f"  {t('skf_knowledge')}: {imp['knowledge']}")
                    self.console.print(f"  {t('skf_experience')}: {imp['experience']}")
                    self.console.print(f"  {t('skf_local_data')}: {imp['local_data']}")
                    self.console.print(f"  {t('skf_skipped')}: {imp['skipped']}")
                    self.console.print(f"  {t('skf_source')}: {imp_result['source_spark']}")
                elif imp_result["status"] == "validation_error":
                    self.console.print(f"[red]✗ {t('skf_validation_failed')}:[/]")
                    for err in imp_result["errors"]:
                        self.console.print(f"  [red]• {err}[/]")
            except Exception as e:
                self.console.print(f"[red]{t('skf_import_failed')}: {e}[/]")
            return

        if subcmd in ("info", "信息") and len(args) > 1:
            path = args[1]
            try:
                pkg = SKFPackage.import_from_file(path)
                stats = pkg.get_stats()
                table = Table(title=t("skf_package_info"))
                table.add_column(t("field_item"), style="cyan")
                table.add_column(t("field_value"))
                table.add_row(t("field_spark_id"), stats["spark_id"])
                table.add_row(t("field_created"), stats["created"])
                table.add_row(t("field_version"), stats["version"])
                table.add_row(t("field_knowledge"), str(stats["knowledge_count"]))
                table.add_row(t("field_experience"), str(stats["experience_count"]))
                table.add_row(t("field_local_data"), str(stats["local_data_count"]))
                if stats["categories"]:
                    table.add_row(t("field_categories"), ", ".join(f"{k}({v})" for k, v in stats["categories"].items()))
                self.console.print(table)

                errors = pkg.validate()
                if errors:
                    self.console.print(f"[yellow]⚠ {t('skf_validation_warnings')}:[/]")
                    for err in errors:
                        self.console.print(f"  [yellow]• {err}[/]")
                else:
                    self.console.print(f"[green]✓ {t('skf_validation_passed')}[/]")
            except Exception as e:
                self.console.print(f"[red]{t('skf_read_failed')}: {e}[/]")
            return

        self.console.print(f"[dim]{t('skf_usage_short')}[/]")


class VerifyCommand(BaseCommand):
    COMMAND_NAME = "verify"
    ALIASES = ("验证",)

    def execute(self, args: list[str]) -> None:
        verifier = self.container.get("knowledge_verifier")
        if verifier is None:
            self.console.print(f"[red]{t('error_service_not_available', name='knowledge_verifier')}[/]")
            return

        if not args:
            self.console.print(f"[bold]{t('verify_title')}[/]")
            self.console.print(f"[dim]{t('verify_usage')}[/]")
            return

        subcmd = args[0].lower()

        if subcmd == "stats":
            rows = self.db.conn.execute(
                "SELECT verification, COUNT(*) as cnt FROM knowledge GROUP BY verification"
            ).fetchall()
            table = Table(title=t("title_verification"))
            table.add_column(t("field_level"), style="cyan")
            table.add_column(t("field_count"), justify="right")
            for r in rows:
                level = r["verification"]
                icon = {"expert_verified": "✅", "cross_ref": "🔍", "field_tested": "🧪",
                        "partially_verified": "⚠️", "unverified": "❓", "conflict": "⛔"}.get(level, "❓")
                table.add_row(f"{icon} {level}", str(r["cnt"]))
            self.console.print(table)
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
            self.console.print(f"[dim]{t('verify_no_entries')}[/]")
            return

        self.console.print(f"[bold]{t('verify_verifying', count=len(entries))}[/]")

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

            self.console.print(f"  {icon} [{report.entry_id}] {report.entry_title[:40]} → {report.level}")
            if report.warnings:
                for w in report.warnings[:2]:
                    self.console.print(f"     [dim]{w}[/]")

        self.console.print(f"\n[green]{t('verify_complete', verified=verified_count, conflicts=conflict_count)}[/]")
