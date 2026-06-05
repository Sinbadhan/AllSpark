from rich.table import Table

from allspark.commands.base import BaseCommand
from allspark.core.i18n import t


class NetworkCommand(BaseCommand):
    COMMAND_NAME = "network"
    ALIASES = ("网络", "net")

    def _get_net(self):
        net = self.container.get("spark_network")
        if not net:
            from allspark.services.spark_network import SparkNetwork
            llm = self.container.get("llm")
            net = SparkNetwork(db=self.db, llm_engine=llm)
            self.container.register("spark_network", net)
        return net

    def execute(self, args: list[str]) -> None:
        net = self._get_net()

        if not args:
            status = net.get_status()
            table = Table(title=t("title_network"))
            table.add_column(t("field_item"), style="cyan")
            table.add_column(t("field_value"))
            table.add_row(t("field_spark_id"), status["spark_id"])
            table.add_row(t("field_discovery"), "🟢 Running" if status["running"] else "🔴 Stopped")
            for ch, avail in status["channels"].items():
                table.add_row(ch, "✅" if avail else "❌")
            table.add_row(t("field_known_nodes"), str(status["known_nodes"]))
            self.console.print(table)

            if status["nodes"]:
                ntable = Table(title=t("known_nodes"))
                ntable.add_column(t("field_name"))
                ntable.add_column(t("field_knowledge"), justify="right")
                ntable.add_column(t("field_status_col"))
                for n in status["nodes"]:
                    ntable.add_row(n["display_name"], str(n["knowledge_count"]), n["status"])
                self.console.print(ntable)

            self.console.print(f"\n[dim]{t('network_usage')}[/]")
            return

        subcmd = args[0].lower()

        if subcmd in ("scan", "扫描", "detect", "检测"):
            with self.console.status(t("scanning_channels")):
                channels = net.detect_channels()
            table = Table(title=t("title_channel"))
            table.add_column(t("field_channel"), style="cyan")
            table.add_column(t("field_available"))
            table.add_column(t("field_details"))
            for ch, info in channels.items():
                avail = info.get("available", False)
                detail = ""
                if ch == "lan" and avail:
                    detail = f"IP: {info.get('ip', '')}"
                table.add_row(ch, "✅" if avail else "❌", detail)
            self.console.print(table)
            return

        if subcmd in ("start", "启动"):
            result = net.start_discovery()
            if result["status"] == "started":
                net.start_exchange_server()
                self.console.print(f"[green]✓ {t('net_discovery_started', id=result['spark_id'])}[/]")
                self.console.print(f"[dim]{t('net_broadcasting')}[/]")
            else:
                self.console.print(f"[yellow]{result.get('message', result['status'])}[/]")
            return

        if subcmd in ("stop", "停止"):
            result = net.stop_discovery()
            self.console.print(f"[green]✓ {t('net_discovery_stopped', count=result['nodes_found'])}[/]")
            return

        if subcmd in ("send", "发送") and len(args) > 2:
            node_id = args[1]
            entry_ids = args[2:]
            result = net.send_knowledge(node_id, entry_ids)
            if result["status"] == "ok":
                self.console.print(f"[green]✓ {t('net_sent_ok', sent=result['sent_count'], accepted=result.get('accepted_count', '?'))}[/]")
            else:
                self.console.print(f"[red]{result.get('message', t('net_send_failed'))}[/]")
            return

        if subcmd in ("exchange", "交换") and len(args) > 1:
            node_id = args[1]
            result = net.request_exchange(node_id)
            if result["status"] == "ok":
                remote = result.get("remote_index", {})
                comp = result.get("complementary", [])
                self.console.print(f"[green]✓ {t('net_handshake_ok')}[/]")
                self.console.print(f"  {t('net_remote_knowledge')}: {remote.get('total', 0)}")
                if comp:
                    self.console.print(f"  {t('net_complementary')}: {', '.join(comp)}")
            else:
                self.console.print(f"[red]{result.get('message', t('net_exchange_failed'))}[/]")
            return

        self.console.print(f"[dim]{t('network_usage_short')}[/]")


class VisionCommand(BaseCommand):
    COMMAND_NAME = "vision"
    ALIASES = ("视觉", "识别")

    def _get_vision(self):
        vision = self.container.get("vision")
        if not vision:
            from allspark.services.vision_engine import VisionEngine
            llm = self.container.get("llm")
            local_vision = self.container.get("local_vision")
            vision = VisionEngine(llm_engine=llm, db=self.db, local_vision=local_vision)
            self.container.register("vision", vision)
        return vision

    def execute(self, args: list[str]) -> None:
        from allspark.services.vision_engine import VisionTask

        vision = self._get_vision()

        if not args:
            status = vision.get_status()
            table = Table(title=t("title_vision"))
            table.add_column(t("field_item"), style="cyan")
            table.add_column(t("field_value"))
            table.add_row(t("field_available"), "✅" if status["available"] else "❌")
            table.add_row(t("field_multimodal"), "✅" if status["multimodal"] else f"❌ ({t('vision_text_fallback')})")
            table.add_row(t("field_llm_model"), status.get("llm_model") or t("field_not_loaded"))
            self.console.print(table)
            self.console.print(f"\n[dim]{t('vision_usage')}[/]")
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
            self.console.print(f"[red]{t('vision_not_available')}[/]")
            return

        with self.console.status(t("analyzing_image")):
            result = vision.analyze_image(image_path, task)

        table = Table(title=f"👁 {t('vision_analysis')}: {task.value}")
        table.add_column(t("field_item"), style="cyan")
        table.add_column(t("field_value"))
        table.add_row(t("field_description"), result.description)
        table.add_row(t("field_confidence"), result.confidence)
        if result.warnings:
            table.add_row(t("field_warnings"), "\n".join(f"⚠ {w}" for w in result.warnings))
        if result.recommendations:
            table.add_row(t("field_recommendations"), "\n".join(f"→ {r}" for r in result.recommendations))
        if result.related_knowledge:
            table.add_row(t("field_related_knowledge"), ", ".join(result.related_knowledge))
        self.console.print(table)
