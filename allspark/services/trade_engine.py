import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from allspark.core.models import TradeOffer, TradeStatus

logger = logging.getLogger(__name__)


class TradeEngine:
    def __init__(self, db=None, network=None, verifier=None):
        self.db = db
        self.network = network
        self.verifier = verifier
        self._offers: dict[str, TradeOffer] = {}
        self._trade_history: list[dict] = []
        self._load_from_db()

    def _load_from_db(self):
        if not self.db:
            return
        try:
            rows = self.db.get_trade_offers()
            for r in rows:
                offer = TradeOffer(
                    id=r["id"],
                    proposer_id=r["proposer_id"],
                    target_spark_id=r["target_spark_id"],
                    offer_knowledge_ids=json.loads(r["offer_knowledge_ids"]) if r["offer_knowledge_ids"] else [],
                    request_knowledge_ids=json.loads(r["request_knowledge_ids"]) if r["request_knowledge_ids"] else [],
                    status=r["status"],
                    created_at=r["created_at"],
                    completed_at=r["completed_at"],
                )
                self._offers[offer.id] = offer
        except Exception as e:
            logger.warning("Failed to load trades from DB: %s", e)

    def propose_trade(self, proposer_id: str, target_spark_id: str,
                      offer_ids: list[str], request_ids: list[str]) -> TradeOffer:
        offer_id = f"trade-{uuid.uuid4().hex[:6]}"
        now = datetime.now().isoformat()

        offer = TradeOffer(
            id=offer_id,
            proposer_id=proposer_id,
            target_spark_id=target_spark_id,
            offer_knowledge_ids=offer_ids,
            request_knowledge_ids=request_ids,
            status=TradeStatus.PROPOSED.value,
            created_at=now,
        )
        self._offers[offer_id] = offer
        self._save_offer(offer)
        return offer

    def accept_trade(self, trade_id: str) -> dict:
        offer = self._offers.get(trade_id)
        if not offer:
            return {"status": "error", "message": "Trade not found"}
        if offer.status != TradeStatus.PROPOSED.value:
            return {"status": "error", "message": f"Trade is {offer.status}, cannot accept"}

        offer.status = TradeStatus.ACCEPTED.value
        self._save_offer(offer)

        result = self._execute_trade(offer)
        return result

    def reject_trade(self, trade_id: str) -> bool:
        offer = self._offers.get(trade_id)
        if not offer:
            return False
        offer.status = TradeStatus.REJECTED.value
        self._save_offer(offer)
        return True

    def cancel_trade(self, trade_id: str) -> bool:
        offer = self._offers.get(trade_id)
        if not offer or offer.status not in (TradeStatus.PROPOSED.value, TradeStatus.ACCEPTED.value):
            return False
        offer.status = TradeStatus.CANCELLED.value
        self._save_offer(offer)
        return True

    def _execute_trade(self, offer: TradeOffer) -> dict:
        if not self.db:
            return {"status": "error", "message": "No database available"}

        from allspark.services.knowledge_verifier import KnowledgeVerifier

        received_entries = []
        rejected_entries = []

        for kid in offer.request_knowledge_ids:
            entry = self.db.get_knowledge(kid)
            if entry:
                received_entries.append(entry)

        if self.verifier:
            verifier = KnowledgeVerifier(self.db)
            for entry in received_entries:
                report = verifier.verify_entry(entry)
                if report.level == "conflict":
                    rejected_entries.append(entry)

        received_entries = [e for e in received_entries if e not in rejected_entries]

        offer.status = TradeStatus.COMPLETED.value
        offer.completed_at = datetime.now().isoformat()
        self._save_offer(offer)

        trade_record = {
            "trade_id": offer.id,
            "proposer": offer.proposer_id,
            "target": offer.target_spark_id,
            "offered": offer.offer_knowledge_ids,
            "received": [e.id for e in received_entries],
            "rejected": [e.id for e in rejected_entries],
            "completed_at": offer.completed_at,
        }
        self._trade_history.append(trade_record)

        return {
            "status": "ok",
            "trade_id": offer.id,
            "received_count": len(received_entries),
            "rejected_count": len(rejected_entries),
            "received_ids": [e.id for e in received_entries],
            "rejected_ids": [e.id for e in rejected_entries],
        }

    def evaluate_trade(self, trade_id: str) -> Optional[dict]:
        offer = self._offers.get(trade_id)
        if not offer:
            return None

        if not self.db:
            return {"trade_id": trade_id, "evaluation": "unknown", "reason": "No database"}

        offer_value = 0
        for kid in offer.offer_knowledge_ids:
            entry = self.db.get_knowledge(kid)
            if entry:
                offer_value += (4 - entry.priority)

        request_value = 0
        for kid in offer.request_knowledge_ids:
            entry = self.db.get_knowledge(kid)
            if entry:
                request_value += (4 - entry.priority)

        missing = []
        for kid in offer.request_knowledge_ids:
            if not self.db.get_knowledge(kid):
                missing.append(kid)

        if offer_value > request_value:
            evaluation = "favorable"
        elif offer_value == request_value:
            evaluation = "balanced"
        else:
            evaluation = "unfavorable"

        if missing:
            evaluation = "valuable"
            reason = f"Offers {len(missing)} knowledge entries you don't have"
        elif offer_value >= request_value:
            reason = "Fair or favorable exchange"
        else:
            reason = "You would give more than you receive"

        return {
            "trade_id": trade_id,
            "evaluation": evaluation,
            "reason": reason,
            "your_offer_value": offer_value,
            "their_offer_value": request_value,
            "new_knowledge_count": len(missing),
        }

    def get_trade(self, trade_id: str) -> Optional[TradeOffer]:
        return self._offers.get(trade_id)

    def get_active_trades(self) -> list[TradeOffer]:
        return [o for o in self._offers.values() if o.status in ("proposed", "accepted")]

    def get_trade_history(self) -> list[dict]:
        return self._trade_history

    def get_all_trades(self) -> list[TradeOffer]:
        return list(self._offers.values())

    def suggest_trades(self, remote_index: dict) -> list[dict]:
        if not self.db:
            return []

        my_categories = set()
        my_categories = set(self.db.get_distinct_knowledge_categories())

        remote_categories = set(remote_index.get("categories", {}).keys())
        complementary = remote_categories - my_categories

        suggestions = []
        for cat in complementary:
            suggestions.append({
                "category": cat,
                "reason": f"You have no knowledge in '{cat}' category",
                "action": "Request all knowledge in this category",
            })

        set(self.db.get_knowledge_ids())

        return suggestions

    def _save_offer(self, offer: TradeOffer):
        if not self.db:
            return
        self.db.upsert_trade_offer(
            offer.id, offer.proposer_id, offer.target_spark_id,
            json.dumps(offer.offer_knowledge_ids, ensure_ascii=False),
            json.dumps(offer.request_knowledge_ids, ensure_ascii=False),
            offer.status, offer.created_at, offer.completed_at
        )

    def get_status(self) -> dict:
        return {
            "total_trades": len(self._offers),
            "active_trades": len([o for o in self._offers.values() if o.status in ("proposed", "accepted")]),
            "completed_trades": len([o for o in self._offers.values() if o.status == "completed"]),
            "history_count": len(self._trade_history),
        }
