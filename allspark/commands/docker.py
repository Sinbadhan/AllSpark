from rich.table import Table
from rich.panel import Panel

from allspark.commands.base import BaseCommand
from allspark.i18n import t


class DockerCommand(BaseCommand):
    COMMAND_NAME = "docker"
    ALIASES = ("容器",)

    def _get_docker_mgr(self):
        mgr = self.container.get("docker_manager")
        if not mgr:
            self.console.print(f"[dim]{t('docker_not_configured')}[/]")
            return None
        return mgr

    def execute(self, args: list[str]) -> None:
        if not args:
            self._show_status()
            return

        sub = args[0].lower()

        if sub in ("status", "状态"):
            self._show_status()
        elif sub in ("start", "启动"):
            service = args[1] if len(args) > 1 else None
            self._start(service)
        elif sub in ("stop", "停止"):
            service = args[1] if len(args) > 1 else None
            self._stop(service)
        elif sub in ("logs", "日志"):
            service = args[1] if len(args) > 1 else None
            lines = int(args[2]) if len(args) > 2 else 50
            self._show_logs(service, lines)
        elif sub in ("migrate", "迁移"):
            target = args[1] if len(args) > 1 else None
            self._migrate(target)
        else:
            self.console.print(f"[yellow]{t('docker_unknown_cmd', cmd=sub)}[/]")

    def _show_status(self):
        mgr = self._get_docker_mgr()
        if not mgr:
            self._show_deploy_mode_only()
            return

        status = mgr.get_status()
        deploy_names = {
            "process": t("deploy_mode_process"),
            "docker": t("deploy_mode_docker"),
            "integration": t("deploy_mode_integration"),
        }

        table = Table(title=t("docker_status_header"))
        table.add_column(t("docker_col_service"), style="cyan")
        table.add_column(t("docker_col_container"))
        table.add_column(t("docker_col_port"))
        table.add_column(t("docker_col_status"))

        services = status.get("services", {})
        for name, info in services.items():
            state = f"[green]{t('docker_state_running')}[/]" if info["running"] else f"[red]{t('docker_state_stopped')}[/]"
            table.add_row(name, info["container"], str(info["port"]), state)

        if not services:
            table.add_row("-", "-", "-", t("docker_no_services"))

        self.console.print(table)
        self.console.print(f"[dim]{t('docker_deploy_mode', mode=deploy_names.get(status['deploy_mode'], status['deploy_mode']))}[/]")

    def _show_deploy_mode_only(self):
        flags = self.container.get("flags")
        if not flags:
            return
        deploy_names = {
            "process": t("deploy_mode_process"),
            "docker": t("deploy_mode_docker"),
            "integration": t("deploy_mode_integration"),
        }
        mode = flags.deploy_mode
        self.console.print(Panel(
            t("docker_deploy_mode", mode=deploy_names.get(mode, mode)),
            title=t("docker_status_header"),
        ))
        if mode == "process":
            self.console.print(f"[dim]{t('docker_process_mode_hint')}[/]")

    def _start(self, service: str = None):
        mgr = self._get_docker_mgr()
        if not mgr:
            return

        if service:
            result = mgr.start_service(service)
        else:
            result = mgr.start_all()

        if result.get("status") == "ok":
            self.console.print(f"[green]✅ {t('docker_start_ok')}[/]")
            if "services" in result:
                for svc, r in result["services"].items():
                    icon = "✅" if r.get("status") == "ok" else "❌"
                    self.console.print(f"  {icon} {svc}")
        else:
            self.console.print(f"[red]❌ {t('docker_start_fail', message=result.get('message', ''))}[/]")

    def _stop(self, service: str = None):
        mgr = self._get_docker_mgr()
        if not mgr:
            return

        if service:
            result = mgr.stop_service(service)
        else:
            result = mgr.stop_all()

        if result.get("status") == "ok":
            self.console.print(f"[green]✅ {t('docker_stop_ok')}[/]")
        else:
            self.console.print(f"[red]❌ {t('docker_stop_fail', message=result.get('message', ''))}[/]")

    def _show_logs(self, service: str, lines: int = 50):
        mgr = self._get_docker_mgr()
        if not mgr:
            return

        if not service:
            self.console.print(f"[yellow]{t('docker_logs_need_service')}[/]")
            return

        logs = mgr.get_logs(service, lines)
        self.console.print(Panel(logs, title=f"{service} logs"))

    def _migrate(self, target: str):
        if not target:
            self.console.print(f"[yellow]{t('docker_migrate_need_target')}[/]")
            return

        mgr = self._get_docker_mgr()
        if not mgr:
            if target in ("docker", "integration"):
                self.console.print(f"[red]❌ {t('docker_not_configured')}[/]")
            return

        if target in ("docker", "integration"):
            result = mgr.migrate_to_docker()
        elif target == "process":
            result = mgr.migrate_to_process()
        else:
            self.console.print(f"[yellow]{t('docker_unknown_target', target=target)}[/]")
            return

        if result.get("status") == "ok":
            self.console.print(f"[green]✅ {t('docker_migrate_ok', mode=result.get('deploy_mode', target))}[/]")
        else:
            self.console.print(f"[red]❌ {t('docker_migrate_fail', message=result.get('message', ''))}[/]")
