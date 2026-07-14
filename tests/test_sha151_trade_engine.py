"""SHA-151: trade_engine line-coverage tests (criterion 1: total line >=75%).

Exercises the propose/accept/reject/cancel/evaluate/suggest flows, _execute_trade
with a verifier rejecting conflicts, _load_from_db, and the status/query helpers.
Uses a real Database + mocked verifier.
"""
from unittest.mock import MagicMock

from allspark.core.database import Database
from allspark.core.models import KnowledgeEntry
from allspark.services.trade_engine import TradeEngine


def _entry(id: str, priority: int = 1) -> KnowledgeEntry:
    return KnowledgeEntry(
        id=id, category="water", subcategory="s", priority=priority,
        title=id, summary="s", steps=[], prerequisites=[], warnings=[],
        verification="unverified", source="pre_collapse", version=1, language="zh",
    )


def _engine(tmp_path, *, with_verifier=False):
    db = Database(tmp_path / "te.db")
    for k in [_entry("k1", priority=0), _entry("k2", priority=2),
              _entry("k3", priority=3), _entry("k4", priority=1)]:
        db.save_knowledge(k)
    verifier = MagicMock() if with_verifier else None
    return db, TradeEngine(db=db, verifier=verifier)


def test_propose_accept_completes_trade(tmp_path):
    db, te = _engine(tmp_path)
    offer = te.propose_trade("local", "remote", ["k1"], ["k2"])
    assert offer.status == "proposed"
    result = te.accept_trade(offer.id)
    assert result["status"] == "ok"
    assert result["received_count"] == 1
    assert te.get_trade(offer.id).status == "completed"
    assert te.get_trade_history()


def test_accept_not_found_and_wrong_status(tmp_path):
    _, te = _engine(tmp_path)
    assert te.accept_trade("nope")["status"] == "error"
    offer = te.propose_trade("local", "remote", ["k1"], ["k2"])
    te.reject_trade(offer.id)
    assert te.accept_trade(offer.id)["status"] == "error"  # rejected, can't accept


def test_reject_and_cancel(tmp_path):
    _, te = _engine(tmp_path)
    assert te.reject_trade("nope") is False
    o1 = te.propose_trade("local", "remote", ["k1"], ["k2"])
    assert te.reject_trade(o1.id) is True
    # cancel: not found / wrong status / ok
    assert te.cancel_trade("nope") is False
    assert te.cancel_trade(o1.id) is False  # already rejected
    o2 = te.propose_trade("local", "remote", ["k1"], ["k2"])
    assert te.cancel_trade(o2.id) is True
    assert te.get_trade(o2.id).status == "cancelled"


def test_execute_trade_with_verifier_rejecting_conflict(tmp_path, monkeypatch):
    db, te = _engine(tmp_path, with_verifier=True)
    # _execute_trade creates a fresh KnowledgeVerifier(self.db) when self.verifier
    # is truthy; monkeypatch its verify_entry to flag k2 as a conflict.
    from allspark.services.knowledge_verifier import KnowledgeVerifier
    report = MagicMock()
    report.level = "conflict"
    monkeypatch.setattr(KnowledgeVerifier, "verify_entry", lambda self, entry: report)
    offer = te.propose_trade("local", "remote", ["k1"], ["k2"])
    result = te.accept_trade(offer.id)
    assert result["rejected_count"] == 1
    assert result["received_count"] == 0


def test_execute_trade_no_db(tmp_path):
    te = TradeEngine(db=None)
    offer = te.propose_trade("local", "remote", ["k1"], ["k2"])
    result = te.accept_trade(offer.id)
    assert result["status"] == "error"
    assert "No database" in result["message"]


def test_evaluate_trade_branches(tmp_path):
    _, te = _engine(tmp_path)
    # not found
    assert te.evaluate_trade("nope") is None
    # favorable: offer k1 (priority 0, value 4) vs request k2 (priority 2, value 2)
    o = te.propose_trade("local", "remote", ["k1"], ["k2"])
    assert te.evaluate_trade(o.id)["evaluation"] == "favorable"
    # balanced: offer k2 (value 2) vs request k4 (priority 1, value 3) -> 2 < 3 unfavorable
    o2 = te.propose_trade("local", "remote", ["k2"], ["k4"])
    assert te.evaluate_trade(o2.id)["evaluation"] == "unfavorable"
    # valuable: request a kid not in db
    o3 = te.propose_trade("local", "remote", ["k1"], ["missing-kid"])
    assert te.evaluate_trade(o3.id)["evaluation"] == "valuable"


def test_evaluate_trade_balanced_and_no_db(tmp_path):
    _, te = _engine(tmp_path)
    # balanced: offer k1 (value 4) vs request k1 (value 4) -- same entry
    o = te.propose_trade("local", "remote", ["k1"], ["k1"])
    assert te.evaluate_trade(o.id)["evaluation"] == "balanced"
    # no db
    te2 = TradeEngine(db=None)
    o2 = te2.propose_trade("local", "remote", ["k1"], ["k2"])
    r = te2.evaluate_trade(o2.id)
    assert r["evaluation"] == "unknown"


def test_suggest_trades_complementary_categories(tmp_path):
    db, te = _engine(tmp_path)
    # remote has categories we lack -> suggestions.
    remote = {"categories": {"fire": {}, "medicine": {}}}
    # db knowledge is all "water" category, so fire/medicine are complementary.
    suggestions = te.suggest_trades(remote)
    assert any(s["category"] in ("fire", "medicine") for s in suggestions)


def test_suggest_trades_no_db():
    te = TradeEngine(db=None)
    assert te.suggest_trades({"categories": {"x": {}}}) == []


def test_load_from_db_loads_existing_offers(tmp_path):
    db, te = _engine(tmp_path)
    te.propose_trade("local", "remote", ["k1"], ["k2"])
    # New engine instance over the same db loads the persisted offer.
    te2 = TradeEngine(db=db)
    assert any(o.id for o in te2.get_all_trades())


def test_load_from_db_handles_corrupt_row(tmp_path):
    db, te = _engine(tmp_path)
    # Insert a row with bad JSON so _load_from_db hits the except branch.
    db.conn.execute(
        "INSERT INTO trade_offers (id, proposer_id, target_spark_id, "
        "offer_knowledge_ids, request_knowledge_ids, status, created_at, completed_at) "
        "VALUES ('bad','l','r','not-json','[]','proposed','t','')"
    )
    db.conn.commit()
    # Constructing a new engine over the corrupt row must not raise.
    TradeEngine(db=db)


def test_status_and_queries(tmp_path):
    _, te = _engine(tmp_path)
    te.propose_trade("local", "remote", ["k1"], ["k2"])
    te.propose_trade("local", "remote2", ["k3"], ["k4"])
    status = te.get_status()
    assert status["total_trades"] == 2
    assert status["active_trades"] == 2
    assert te.get_active_trades()  # both proposed
    assert te.get_all_trades()  # all
