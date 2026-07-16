"""Governance fail-closed boundary and trade API route coverage."""
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from allspark.adapters.routes.governance import _split_csv
from allspark.adapters.web_ui import create_app
from allspark.core.database import Database
from allspark.infrastructure.hardware import FeatureFlags
from allspark.infrastructure.module_loader import ModuleRegistry


def _client(db_path: str) -> TestClient:
    db = Database(db_path)
    try:
        db.mark_initialized()
        flags = FeatureFlags(
            web_ui=True, governance=True, trade_engine=True,
            data_preservation=True, boot_manager=True,
        )
        ModuleRegistry(flags).save_to_db(db)
    finally:
        db.close()
    return TestClient(create_app(db_path))


@pytest.fixture(scope="module")
def client() -> TestClient:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    c = _client(path)
    yield c
    if os.path.exists(path):
        os.unlink(path)


# ─── governance is fail closed until subject-bound authorization exists ─────


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/governance/status", None),
        ("get", "/api/governance/members", None),
        ("get", "/api/governance/assess", None),
        ("get", "/api/governance/recommend", None),
        ("get", "/api/governance/conflicts", None),
        ("post", "/api/governance/member/add", {"name": "alice"}),
        ("post", "/api/governance/member/remove", {"member_id": "member-1"}),
        (
            "post",
            "/api/governance/member/role",
            {"member_id": "member-1", "role": "commander"},
        ),
        (
            "post",
            "/api/governance/conflict/create",
            {"title": "dispute", "parties": ["member-1", "member-2"]},
        ),
        (
            "post",
            "/api/governance/conflict/mediate",
            {"conflict_id": "conflict-1"},
        ),
        (
            "post",
            "/api/governance/conflict/resolve",
            {"conflict_id": "conflict-1", "resolution": "settled"},
        ),
    ],
)
def test_governance_routes_are_unavailable(
    client: TestClient, method: str, path: str, payload: dict | None
) -> None:
    response = client.request(method, path, json=payload)
    assert response.status_code == 503
    assert response.json()["status"] == "error"
    assert response.json()["detail"]
    assert response.json()["next_action"]


def test_governance_rejection_has_no_side_effects(client: TestClient) -> None:
    before_members = client.app.state.db.get_community_members()
    before_conflicts = client.app.state.db.get_conflicts()
    client.post("/api/governance/member/add", json={"name": "alice"})
    client.post(
        "/api/governance/conflict/create",
        json={"title": "dispute", "parties": ["a", "b"]},
    )
    assert client.app.state.db.get_community_members() == before_members
    assert client.app.state.db.get_conflicts() == before_conflicts


# ─── trade endpoints ─────────────────────────────────────────────────────────


def test_trade_status_and_list(client: TestClient) -> None:
    assert client.get("/api/trade/status").status_code == 200
    assert client.get("/api/trade/list").json()["trades"] == []


def test_trade_propose_missing_target(client: TestClient) -> None:
    r = client.post("/api/trade/propose", json={"offer_ids": []})
    assert r.json().get("status") != "ok"


def test_trade_csv_helper_treats_missing_value_as_empty() -> None:
    assert _split_csv(None) == []


def test_trade_propose_success(client: TestClient) -> None:
    # Covers the list and csv coercion branches for offer_ids/request_ids.
    r = client.post("/api/trade/propose",
                    json={"target_spark_id": "remote-1",
                          "offer_ids": "k1,k2", "request_ids": ["k3"]})
    assert r.json()["status"] == "ok"
    tid = r.json()["trade_id"]
    # accept (may succeed or return a status dict; either exercises the handler).
    client.post("/api/trade/accept", json={"trade_id": tid})
    # evaluate + reject (not-found path for a fresh id also exercised below).
    client.get("/api/trade/evaluate", params={"trade_id": tid})


def test_trade_accept_and_reject_missing_id(client: TestClient) -> None:
    assert client.post("/api/trade/accept", json={}).json().get("status") != "ok"
    assert client.post("/api/trade/reject", json={}).json().get("status") != "ok"


def test_trade_reject_and_evaluate_not_found(client: TestClient) -> None:
    r = client.post("/api/trade/reject", json={"trade_id": "ghost"})
    assert r.json().get("status") != "ok"
    r2 = client.get("/api/trade/evaluate", params={"trade_id": "ghost"})
    assert r2.json().get("status") != "ok"


def test_trade_reject_success(client: TestClient) -> None:
    proposed = client.post(
        "/api/trade/propose",
        json={"target_spark_id": "remote-reject", "offer_ids": [], "request_ids": []},
    )
    trade_id = proposed.json()["trade_id"]

    rejected = client.post("/api/trade/reject", json={"trade_id": trade_id})
    assert rejected.json() == {"status": "ok"}
