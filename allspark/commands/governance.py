from rich.table import Table

from allspark.commands.base import BaseCommand
from allspark.core.i18n import t
from allspark.infrastructure.module_loader import PRODUCT_DISABLED_MODULES


class GovernanceCommand(BaseCommand):
    COMMAND_NAME = "community"
    ALIASES = ("社区", "gov", "成员")

    def _get_gov(self):
        if "governance" in PRODUCT_DISABLED_MODULES:
            return None
        gov = self.container.get("governance")
        return gov

    def execute(self, args: list[str]) -> None:
        if args and args[0].lower() in ("value", "价值"):
            self.console.print(f"[yellow]{t('survival_value_removed')}[/]")
            self.console.print(f"[dim]{t('survival_value_removed_detail')}[/]")
            return

        gov = self._get_gov()
        if gov is None:
            self.console.print(f"[yellow]{t('governance_access_unavailable')}[/]")
            return

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
            self.console.print(table)
            self.console.print(f"\n[dim]{t('governance_usage')}[/]")
            return

        sub = args[0].lower()

        if sub in ("add", "添加"):
            name = args[1] if len(args) > 1 else t("default_unknown_name")
            role = args[2] if len(args) > 2 else "executor"
            member = gov.add_member(name, role=role)
            self.console.print(f"[green]{t('community_member_added', name=member.name, id=member.id, role=member.role)}[/]")

        elif sub in ("remove", "移除", "删除"):
            mid = args[1] if len(args) > 1 else ""
            if gov.remove_member(mid):
                self.console.print(f"[green]{t('community_member_removed', id=mid)}[/]")
            else:
                self.console.print(f"[red]{t('community_cannot_remove', id=mid)}[/]")

        elif sub in ("role", "角色", "assign"):
            mid = args[1] if len(args) > 1 else ""
            role = args[2] if len(args) > 2 else ""
            if gov.assign_role(mid, role):
                self.console.print(f"[green]{t('community_role_updated', id=mid, role=role)}[/]")
            else:
                self.console.print(f"[red]{t('community_cannot_assign', id=mid)}[/]")

        elif sub in ("list", "列表", "ls"):
            members = gov.get_all_members()
            if not members:
                self.console.print(f"[yellow]{t('community_no_members')}[/]")
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
            self.console.print(table)

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
            self.console.print(table)
            if result["recommendations"]:
                self.console.print(f"[bold]{t('recommendations')}[/]")
                for r in result["recommendations"]:
                    self.console.print(f"  ⚠ {r}")

        elif sub in ("recommend", "推荐"):
            recs = gov.recommend_roles()
            if not recs:
                self.console.print(f"[green]{t('no_role_changes')}[/]")
            else:
                for r in recs:
                    self.console.print(f"  📋 {r['member_name']} ({r['member_id']}): {r['current_role']} → {r['recommended_role']}")
                    self.console.print(f"     [dim]{r['reason']}[/]")

        elif sub in ("conflict", "冲突"):
            title = args[1] if len(args) > 1 else "Untitled"
            parties = args[2:] if len(args) > 2 else []
            conflict = gov.create_conflict(title, "", parties)
            self.console.print(f"[yellow]{t('governance_conflict_recorded', id=conflict.id)}[/]")

        elif sub in ("mediate", "调解"):
            cid = args[1] if len(args) > 1 else ""
            result = gov.mediate_conflict(cid)
            if not result:
                self.console.print(f"[red]{t('governance_conflict_not_found', id=cid)}[/]")
                return
            self.console.print(f"[cyan]{t('governance_mediation_for', id=result['conflict_id'])}[/]")
            for s in result["strategies"]:
                self.console.print(f"  • {s['type']}: {s['description']}")
            if "ai_suggestion" in result:
                self.console.print(f"\n[bold]{t('field_ai_suggestion')}:[/]\n{result['ai_suggestion']}")

        elif sub in ("resolve", "解决"):
            cid = args[1] if len(args) > 1 else ""
            resolution = " ".join(args[2:]) if len(args) > 2 else "Resolved"
            if gov.resolve_conflict(cid, resolution):
                self.console.print(f"[green]{t('governance_conflict_resolved', id=cid)}[/]")
            else:
                self.console.print(f"[red]{t('governance_cannot_resolve', id=cid)}[/]")

        else:
            self.console.print(f"[yellow]{t('governance_unknown_cmd', cmd=sub)}[/]")


class TradeCommand(BaseCommand):
    COMMAND_NAME = "trade"
    ALIASES = ("交易",)

    def _get_trade(self):
        trade = self.container.get("trade_engine")
        if not trade:
            from allspark.services.trade_engine import TradeEngine
            trade = TradeEngine(db=self.db)
            self.container.register("trade_engine", trade)
        return trade

    def execute(self, args: list[str]) -> None:
        trade = self._get_trade()

        if not args:
            status = trade.get_status()
            table = Table(title=t("title_trade"))
            table.add_column(t("field_item"), style="cyan")
            table.add_column(t("field_value"))
            table.add_row(t("field_total_trades"), str(status["total_trades"]))
            table.add_row(t("field_active"), str(status["active_trades"]))
            table.add_row(t("field_completed"), str(status["completed_trades"]))
            self.console.print(table)
            self.console.print(f"\n[dim]{t('trade_usage')}[/]")
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
            self.console.print(table)
            self.console.print(f"\n[dim]{t('trade_usage')}[/]")
            return

        if sub in ("propose", "提议", "发起"):
            target = args[1] if len(args) > 1 else ""
            offer_ids = args[2].split(",") if len(args) > 2 else []
            request_ids = args[3].split(",") if len(args) > 3 else []
            offer = trade.propose_trade("local", target, offer_ids, request_ids)
            self.console.print(f"[green]{t('trade_proposed', id=offer.id)}[/]")
            self.console.print(f"  Offer: {offer.offer_knowledge_ids}")
            self.console.print(f"  Request: {offer.request_knowledge_ids}")

        elif sub in ("accept", "接受"):
            tid = args[1] if len(args) > 1 else ""
            result = trade.accept_trade(tid)
            if result.get("status") == "ok":
                self.console.print(f"[green]{t('trade_completed', count=result['received_count'])}[/]")
                if result.get("rejected_count", 0) > 0:
                    self.console.print(f"[yellow]{t('trade_entries_rejected', count=result['rejected_count'])}[/]")
            else:
                self.console.print(f"[red]❌ {result.get('message', t('trade_failed'))}[/]")

        elif sub in ("reject", "拒绝"):
            tid = args[1] if len(args) > 1 else ""
            if trade.reject_trade(tid):
                self.console.print(f"[yellow]{t('trade_rejected', id=tid)}[/]")
            else:
                self.console.print(f"[red]{t('trade_not_found', id=tid)}[/]")

        elif sub in ("cancel", "取消"):
            tid = args[1] if len(args) > 1 else ""
            if trade.cancel_trade(tid):
                self.console.print(f"[yellow]{t('trade_cancelled', id=tid)}[/]")
            else:
                self.console.print(f"[red]{t('trade_cannot_cancel', id=tid)}[/]")

        elif sub in ("evaluate", "评估"):
            tid = args[1] if len(args) > 1 else ""
            result = trade.evaluate_trade(tid)
            if not result:
                self.console.print(f"[red]{t('trade_not_found', id=tid)}[/]")
                return
            table = Table(title=t("trade_eval_title", id=tid))
            table.add_column(t("field_item"), style="cyan")
            table.add_column(t("field_value"))
            table.add_row(t("field_evaluation"), result["evaluation"])
            table.add_row(t("field_reason"), result["reason"])
            table.add_row(t("field_your_value"), str(result["your_offer_value"]))
            table.add_row(t("field_their_value"), str(result["their_offer_value"]))
            table.add_row(t("field_new_knowledge"), str(result["new_knowledge_count"]))
            self.console.print(table)

        elif sub in ("list", "列表", "ls"):
            trades = trade.get_active_trades()
            if not trades:
                self.console.print(f"[green]{t('no_active_trades')}[/]")
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
            self.console.print(table)

        elif sub in ("history", "历史"):
            history = trade.get_trade_history()
            if not history:
                self.console.print(f"[dim]{t('no_trade_history')}[/]")
                return
            for h in history:
                self.console.print(f"  {h['trade_id']}: {h['proposer']} ↔ {h['target']} | received: {h['received']}")

        else:
            self.console.print(f"[yellow]{t('trade_unknown_cmd', cmd=sub)}[/]")
            self.console.print(f"\n[dim]{t('trade_usage')}[/]")
