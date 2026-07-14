"""SHA-151 Phase B2: governance & trade API route coverage.

The governance routes (adapters/routes/governance.py) were at 0% branch because
test_governance.py only exercised the service layer, not the FastAPI handlers.
These tests drive every endpoint through TestClient to cover the validation,
success, and not-found branches in the route handlers themselves.
"""
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

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


def _add_member(c: TestClient, name: str = "alice", role: str = "executor",
                domains=None) -> dict:
    payload = {"name": name, "role": role}
    if domains is not None:
        payload["domains"] = domains
    r = c.post("/api/governance/member/add", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


# ─── governance status / members / assess / recommend ───────────────────────


def test_governance_status(client: TestClient) -> None:
    r = client.get("/api/governance/status")
    assert r.status_code == 200


def test_governance_members_empty_then_added(client: TestClient) -> None:
    assert client.get("/api/governance/members").json()["members"] == []
    _add_member(client, name="bob")
    members = client.get("/api/governance/members").json()["members"]
    assert any(m["name"] == "bob" for m in members)


def test_governance_assess_and_recommend(client: TestClient) -> None:
    assert client.get("/api/governance/assess").status_code == 200
    assert "recommendations" in client.get("/api/governance/recommend").json()


# ─── member add (validation + csv domains) ───────────────────────────────────


def test_member_add_missing_name_returns_error(client: TestClient) -> None:
    r = client.post("/api/governance/member/add", json={"role": "executor"})
    # error_response returns HTTP 400 with an error body.
    assert r.status_code == 400
    assert r.json().get("status") != "ok"


def test_member_add_csv_domains_string(client: TestClient) -> None:
    # Covers the `isinstance(domains, str)` -> _split_csv branch.
    r = client.post("/api/governance/member/add",
                    json={"name": "carol", "domains": "water,fire,food"})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ─── member remove (validation + not-found) ──────────────────────────────────


def test_member_remove_missing_id(client: TestClient) -> None:
    r = client.post("/api/governance/member/remove", json={})
    assert r.status_code == 400
    assert r.json().get("status") != "ok"


def test_member_remove_not_found(client: TestClient) -> None:
    r = client.post("/api/governance/member/remove", json={"member_id": "nope"})
    assert r.status_code == 400
    assert r.json().get("status") != "ok"


def test_member_remove_existing(client: TestClient) -> None:
    m = _add_member(client, name="dave")
    r = client.post("/api/governance/member/remove", json={"member_id": m["member"]["id"]})
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


# ─── member role (validation + csv + not-found) ──────────────────────────────


def test_member_role_missing_fields(client: TestClient) -> None:
    r = client.post("/api/governance/member/role", json={"member_id": "x"})
    assert r.json().get("status") != "ok"


def test_member_role_assign_success(client: TestClient) -> None:
    m = _add_member(client, name="erin")
    r = client.post("/api/governance/member/role",
                    json={"member_id": m["member"]["id"], "role": "medic",
                          "domains": "medical,first_aid"})
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_member_role_invalid_member(client: TestClient) -> None:
    r = client.post("/api/governance/member/role",
                    json={"member_id": "ghost", "role": "medic"})
    assert r.json().get("status") != "ok"


# ─── survival-value (success + not-found) ────────────────────────────────────


def test_survival_value_success(client: TestClient) -> None:
    m = _add_member(client, name="frank")
    r = client.get("/api/governance/survival-value", params={"member_id": m["member"]["id"]})
    assert r.status_code == 200


def test_survival_value_not_found(client: TestClient) -> None:
    r = client.get("/api/governance/survival-value", params={"member_id": "ghost"})
    assert r.json().get("status") != "ok"


# ─── conflict create / mediate / resolve / list ──────────────────────────────


def test_conflict_create_missing_fields(client: TestClient) -> None:
    r = client.post("/api/governance/conflict/create", json={"title": "t"})
    assert r.json().get("status") != "ok"


def test_conflict_create_and_resolve(client: TestClient) -> None:
    a = _add_member(client, name="g1")
    b = _add_member(client, name="g2")
    r = client.post("/api/governance/conflict/create",
                    json={"title": "dispute", "parties": [a["member"]["id"], b["member"]["id"]]})
    assert r.json()["status"] == "ok"
    cid = r.json()["conflict_id"]

    # mediate
    m = client.post("/api/governance/conflict/mediate", json={"conflict_id": cid})
    assert m.status_code == 200

    # resolve
    res = client.post("/api/governance/conflict/resolve",
                      json={"conflict_id": cid, "resolution": "settled"})
    assert res.json().get("status") == "ok"

    # list
    conflicts = client.get("/api/governance/conflicts").json()["conflicts"]
    assert any(c["id"] == cid for c in conflicts)


def test_conflict_create_csv_parties(client: TestClient) -> None:
    a = _add_member(client, name="h1")
    b = _add_member(client, name="h2")
    # Covers the `isinstance(parties_raw, list)` false -> _split_csv branch.
    r = client.post("/api/governance/conflict/create",
                    json={"title": "csv", "parties": f"{a['member']['id']},{b['member']['id']}"})
    assert r.json()["status"] == "ok"


def test_conflict_mediate_missing_id_and_not_found(client: TestClient) -> None:
    assert client.post("/api/governance/conflict/mediate", json={}).json().get("status") != "ok"
    assert client.post("/api/governance/conflict/mediate",
                       json={"conflict_id": "ghost"}).json().get("status") != "ok"


def test_conflict_resolve_missing_id(client: TestClient) -> None:
    r = client.post("/api/governance/conflict/resolve", json={})
    assert r.json().get("status") != "ok"


# ─── trade endpoints ─────────────────────────────────────────────────────────


def test_trade_status_and_list(client: TestClient) -> None:
    assert client.get("/api/trade/status").status_code == 200
    assert client.get("/api/trade/list").json()["trades"] == []


def test_trade_propose_missing_target(client: TestClient) -> None:
    r = client.post("/api/trade/propose", json={"offer_ids": []})
    assert r.json().get("status") != "ok"


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
