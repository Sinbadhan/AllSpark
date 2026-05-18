from rich.table import Table
from rich.panel import Panel

from allspark.commands.base import BaseCommand
from allspark.i18n import t, get_language



class PowerCommand(BaseCommand):
    COMMAND_NAME = "power"
    ALIASES = ("电力", "电量")

    def _get_pm(self):
        pm = self.container.get("power_monitor")
        if not pm:
            from allspark.power_monitor import PowerMonitor
            pm = PowerMonitor(db=self.db)
            self.container.register("power_monitor", pm)
        return pm

    def execute(self, args: list[str]) -> None:
        pm = self._get_pm()

        if not args:
            status = pm.get_status()
            reading = pm.get_current_reading()
            table = Table(title=t("power_monitor"))
            table.add_column(t("field_item"), style="cyan")
            table.add_column(t("field_value"))
            table.add_row(t("field_monitoring"), f"✅ {t('field_active_status')}" if status["monitoring"] else f"❌ {t('field_stopped')}")
            table.add_row(t("field_gpio"), "✅" if status["gpio_available"] else "❌")
            table.add_row(t("field_voltage"), f"{reading.voltage_v}V")
            table.add_row(t("field_current"), f"{reading.current_a}A")
            table.add_row(t("field_power"), f"{reading.power_w}W")
            table.add_row(t("field_energy"), f"{reading.energy_wh}Wh")
            table.add_row(t("field_battery"), f"{reading.battery_percent}%")
            table.add_row(t("field_charging"), "✅" if reading.charging else "❌")
            table.add_row(t("field_source"), reading.source)
            self.console.print(table)

            if reading.source == "no_data":
                self.console.print(f"[dim]{t('power_no_data')}[/]")
            elif reading.source == "from_db":
                self.console.print(f"[dim]{t('power_from_db')}[/]")

            runtime = pm.estimate_runtime()
            if "estimated_hours" in runtime:
                self.console.print(f"\n[dim]{t('est_runtime', hours=runtime['estimated_hours'], mode=runtime.get('mode_recommendation', '?'))}[/]")

            self.console.print(f"\n[dim]{t('power_usage')}[/]")
            return

        sub = args[0].lower()

        if sub in ("start", "开始"):
            interval = int(args[1]) if len(args) > 1 else 60
            result = pm.start_monitoring(interval)
            self.console.print(f"[green]✅ {t('power_monitor_started', interval=interval)}[/]")
        elif sub in ("stop", "停止"):
            pm.stop_monitoring()
            self.console.print(f"[yellow]{t('power_monitor_stopped')}[/]")
        elif sub in ("input", "手动", "输入"):
            wh = float(args[1]) if len(args) > 1 else 0
            charging = len(args) > 2 and args[2].lower() in ("true", "yes", "1", "charging", "充电")
            result = pm.manual_input(wh, charging)
            self.console.print(f"[green]{t('power_updated', wh=wh, battery=result['reading']['battery_percent'])}[/]")
        elif sub in ("source", "电源"):
            if len(args) >= 4 and args[1].lower() in ("add", "添加"):
                pm.register_source(args[2], args[3])
                self.console.print(f"[green]{t('power_source_registered', name=args[2], type=args[3])}[/]")
            else:
                sources = pm.get_sources()
                if sources:
                    for s in sources:
                        icon = "🟢" if s.available else "🔴"
                        self.console.print(f"  {icon} {s.name} ({s.type}): {s.power_w}W")
                else:
                    self.console.print(f"[dim]{t('power_no_sources')}[/]")
        elif sub in ("history", "历史"):
            history = pm.get_history(20)
            if history:
                for h in history[-10:]:
                    self.console.print(f"  {h['timestamp'][:19]}: {h['energy_wh']}Wh {h['battery_percent']}%")
            else:
                self.console.print(f"[dim]{t('power_no_history')}[/]")
        else:
            self.console.print(f"[yellow]{t('power_unknown_cmd', cmd=sub)}[/]")


class SensorCommand(BaseCommand):
    COMMAND_NAME = "sensor"
    ALIASES = ("传感器", "sensors")

    def _get_hub(self):
        hub = self.container.get("sensor_hub")
        if not hub:
            from allspark.sensor_hub import SensorHub
            hub = SensorHub(db=self.db)
            self.container.register("sensor_hub", hub)
        return hub

    def execute(self, args: list[str]) -> None:
        hub = self._get_hub()

        if not args:
            status = hub.get_status()
            snap = hub.get_snapshot()
            table = Table(title=t("sensor_hub"))
            table.add_column(t("field_item"), style="cyan")
            table.add_column(t("field_value"))
            table.add_row(t("field_polling"), f"✅ {t('field_active_status')}" if status["polling"] else f"❌ {t('field_stopped')}")
            table.add_row(t("field_i2c"), "✅" if status["i2c_available"] else "❌")
            table.add_row(t("field_gpio"), "✅" if status["gpio_available"] else "❌")
            table.add_row(t("field_devices"), str(status["devices_registered"]))
            if snap.temperature_c is not None:
                table.add_row(t("temperature"), f"{snap.temperature_c}°C")
            if snap.humidity_pct is not None:
                table.add_row(t("humidity"), f"{snap.humidity_pct}%")
            if snap.pressure_hpa is not None:
                table.add_row(t("pressure"), f"{snap.pressure_hpa}hPa")
            if snap.light_lux is not None:
                table.add_row(t("light"), f"{snap.light_lux}lux")
            self.console.print(table)

            if status["devices_registered"] == 0:
                self.console.print(f"[dim]{t('sensor_no_devices')}[/]")

            self.console.print(f"\n[dim]{t('sensor_usage')}[/]")
            return

        sub = args[0].lower()

        if sub in ("list", "列表", "ls"):
            devices = hub.get_all_devices()
            if not devices:
                self.console.print(f"[dim]{t('sensor_no_registered')}[/]")
                return
            table = Table(title=t("sensor_devices"))
            table.add_column(t("sensor_name"), style="cyan")
            table.add_column(t("sensor_type"))
            table.add_column(t("sensor_interface"))
            table.add_column(t("sensor_last_value"))
            for d in devices:
                val = f"{d['last_value']} {d['last_unit']}" if d['last_value'] is not None else "-"
                table.add_row(d["name"], d["type"], d["interface"], val)
            self.console.print(table)
        elif sub in ("add", "添加"):
            name = args[1] if len(args) > 1 else "sensor"
            stype = args[2] if len(args) > 2 else "temperature"
            hub.register_device(name, stype)
            self.console.print(f"[green]{t('sensor_registered', name=name, type=stype)}[/]")
        elif sub in ("start", "开始"):
            hub.start_polling()
            self.console.print(f"[green]{t('sensor_polling_started')}[/]")
        elif sub in ("stop", "停止"):
            hub.stop_polling()
            self.console.print(f"[yellow]{t('sensor_polling_stopped')}[/]")
        elif sub in ("input", "手动"):
            name = args[1] if len(args) > 1 else ""
            value = float(args[2]) if len(args) > 2 else 0
            reading = hub.manual_input(name, value)
            if reading:
                self.console.print(f"[green]✅ {name}: {reading.value}{reading.unit}[/]")
            else:
                self.console.print(f"[red]{t('sensor_device_not_found', name=name)}[/]")
        elif sub in ("detect", "检测"):
            detected = hub.auto_detect()
            self.console.print(f"[cyan]{t('field_auto_detect_found', count=len(detected))}[/]")
            for d in detected:
                self.console.print(f"  📡 {d['name']} ({d['type']}) via {d['interface']} @ {d['address']}")
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
                table.add_row(t("field_gps"), f"{snap.latitude}, {snap.longitude}")
            if snap.light_lux is not None:
                table.add_row(t("light"), f"{snap.light_lux}lux")
            if snap.air_quality_ppm is not None:
                table.add_row(t("air_quality"), f"{snap.air_quality_ppm}ppm")
            self.console.print(table)
        else:
            self.console.print(f"[yellow]{t('sensor_unknown_cmd', cmd=sub)}[/]")


class PreserveCommand(BaseCommand):
    COMMAND_NAME = "preserve"
    ALIASES = ("固化", "backup", "备份")

    def _get_dp(self):
        dp = self.container.get("data_preservation")
        if not dp:
            from allspark.data_preservation import DataPreservation
            dp = DataPreservation(db=self.db)
            self.container.register("data_preservation", dp)
        return dp

    def execute(self, args: list[str]) -> None:
        dp = self._get_dp()

        if not args:
            status = dp.get_status()
            table = Table(title=t("data_preservation"))
            table.add_column(t("field_item"), style="cyan")
            table.add_column(t("field_value"))
            table.add_row(t("field_auto_save"), f"✅ {t('field_active_status')}" if status["auto_save_running"] else f"❌ {t('field_stopped')}")
            table.add_row(t("field_interval"), f"{status['auto_save_interval_s']}s")
            table.add_row(t("field_last_save"), status.get("last_save_time") or t("field_never"))
            table.add_row(t("field_total_saves"), str(status["total_saves"]))
            table.add_row(t("field_db_size"), f"{status['db_size_mb']}MB")
            table.add_row(t("field_backups"), str(status["backup_count"]))
            table.add_row(t("field_snapshots"), str(status["snapshot_count"]))
            self.console.print(table)
            self.console.print(f"\n[dim]{t('preserve_usage')}[/]")
            return

        sub = args[0].lower()

        if sub in ("start", "开始"):
            interval = int(args[1]) if len(args) > 1 else 300
            dp.start_auto_save(interval)
            self.console.print(f"[green]✅ {t('preserve_auto_started', interval=interval)}[/]")
        elif sub in ("stop", "停止"):
            dp.stop_auto_save()
            self.console.print(f"[yellow]{t('preserve_auto_stopped')}[/]")
        elif sub in ("emergency", "紧急"):
            result = dp.emergency_save("manual")
            if result.get("status") == "ok":
                self.console.print(f"[green]✅ {t('preserve_emergency_ok')}: {result.get('path', '')}[/]")
            else:
                self.console.print(f"[red]❌ {t('preserve_emergency_fail')}: {result.get('message', '')}[/]")
        elif sub in ("snapshot", "快照"):
            label = args[1] if len(args) > 1 else ""
            result = dp.create_snapshot(label)
            if result.get("status") == "ok":
                self.console.print(f"[green]✅ {t('preserve_snapshot_ok')}: {result['meta']['label'] or 'unnamed'} ({result['meta']['db_size_mb']}MB)[/]")
            else:
                self.console.print(f"[red]❌ {t('preserve_snapshot_fail')}: {result.get('message', '')}[/]")
        elif sub in ("snapshots", "快照列表"):
            snapshots = dp.list_snapshots()
            if not snapshots:
                self.console.print(f"[dim]{t('preserve_no_snapshots')}[/]")
            else:
                for s in snapshots:
                    self.console.print(f"  📦 {s.get('label', 'unnamed')} | {s['created']} | {s['db_size_mb']}MB")
        elif sub in ("restore", "恢复"):
            path_or_label = " ".join(args[1:]) if len(args) > 1 else ""
            result = dp.restore_snapshot(path_or_label)
            if result.get("status") == "ok":
                self.console.print(f"[green]{t('preserve_restored', source=result['restored_from'])}[/]")
                self.console.print(f"[yellow]{t('preserve_restart_needed')}[/]")
            else:
                self.console.print(f"[red]{t('preserve_restore_failed', message=result.get('message', ''))}[/]")
        else:
            self.console.print(f"[yellow]{t('preserve_unknown_cmd', cmd=sub)}[/]")
