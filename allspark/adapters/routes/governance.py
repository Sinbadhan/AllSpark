"""Governance and Trade API routes."""

from fastapi import Query

from allspark.adapters.routes.helpers import _require_service


def register_governance_routes(app, check):
    @app.get("/api/governance/status")
    async def governance_status():
        container, db = check()
        gov_svc = _require_service(app, 'governance')
        return gov_svc.get_status()

    @app.post("/api/governance/member/add")
    async def governance_member_add(
        name: str = Query(...),
        role: str = Query("executor"),
        domains: str = Query(""),
    ):
        container, db = check()
        gov_svc = _require_service(app, 'governance')
        domain_list = [d.strip() for d in domains.split(",") if d.strip()] if domains else []
        member = gov_svc.add_member(name, role=role, domains=domain_list)
        return {"status": "ok", "member": {"id": member.id, "name": member.name, "role": member.role, "is_commander": member.is_commander}}

    @app.post("/api/governance/member/remove")
    async def governance_member_remove(member_id: str = Query(...)):
        container, db = check()
        gov_svc = _require_service(app, 'governance')
        if gov_svc.remove_member(member_id):
            return {"status": "ok"}
        return {"status": "error", "message": "Cannot remove member"}

    @app.post("/api/governance/member/role")
    async def governance_member_role(
        member_id: str = Query(...),
        role: str = Query(...),
        domains: str = Query(""),
    ):
        container, db = check()
        gov_svc = _require_service(app, 'governance')
        domain_list = [d.strip() for d in domains.split(",") if d.strip()] if domains else None
        if gov_svc.assign_role(member_id, role, domain_list):
            return {"status": "ok"}
        return {"status": "error", "message": "Cannot assign role"}

    @app.get("/api/governance/members")
    async def governance_members():
        container, db = check()
        gov_svc = _require_service(app, 'governance')
        members = gov_svc.get_all_members()
        return {"members": [
            {"id": m.id, "name": m.name, "role": m.role, "domains": m.domains,
             "skills": m.skills, "health_status": m.health_status,
             "psychological_stability": m.psychological_stability,
             "contribution_score": m.contribution_score,
             "is_commander": m.is_commander}
            for m in members
        ]}

    @app.get("/api/governance/assess")
    async def governance_assess():
        container, db = check()
        gov_svc = _require_service(app, 'governance')
        return gov_svc.assess_organization()

    @app.get("/api/governance/recommend")
    async def governance_recommend():
        container, db = check()
        gov_svc = _require_service(app, 'governance')
        return {"recommendations": gov_svc.recommend_roles()}

    @app.get("/api/governance/survival-value")
    async def governance_survival_value(member_id: str = Query(...)):
        container, db = check()
        gov_svc = _require_service(app, 'governance')
        result = gov_svc.calculate_survival_value(member_id)
        if not result:
            return {"status": "error", "message": "Member not found"}
        return result

    @app.post("/api/governance/conflict/create")
    async def governance_conflict_create(
        title: str = Query(...),
        parties: str = Query(...),
    ):
        container, db = check()
        gov_svc = _require_service(app, 'governance')
        party_list = [p.strip() for p in parties.split(",") if p.strip()]
        conflict = gov_svc.create_conflict(title, "", party_list)
        return {"status": "ok", "conflict_id": conflict.id}

    @app.post("/api/governance/conflict/mediate")
    async def governance_conflict_mediate(conflict_id: str = Query(...)):
        container, db = check()
        gov_svc = _require_service(app, 'governance')
        result = gov_svc.mediate_conflict(conflict_id)
        if not result:
            return {"status": "error", "message": "Conflict not found"}
        return result

    @app.post("/api/governance/conflict/resolve")
    async def governance_conflict_resolve(
        conflict_id: str = Query(...),
        resolution: str = Query("Resolved"),
    ):
        container, db = check()
        gov_svc = _require_service(app, 'governance')
        if gov_svc.resolve_conflict(conflict_id, resolution):
            return {"status": "ok"}
        return {"status": "error", "message": "Cannot resolve conflict"}

    @app.get("/api/governance/conflicts")
    async def governance_conflicts():
        container, db = check()
        gov_svc = _require_service(app, 'governance')
        conflicts = gov_svc.get_all_conflicts()
        return {"conflicts": [
            {"id": c.id, "title": c.title, "parties": c.parties,
             "status": c.status, "mediator": c.mediator,
             "resolution": c.resolution, "created_at": c.created_at,
             "resolved_at": c.resolved_at}
            for c in conflicts
        ]}

    @app.get("/api/trade/status")
    async def trade_status():
        container, db = check()
        trade_svc = _require_service(app, 'trade_engine')
        return trade_svc.get_status()

    @app.post("/api/trade/propose")
    async def trade_propose(
        target_spark_id: str = Query(...),
        offer_ids: str = Query(""),
        request_ids: str = Query(""),
    ):
        container, db = check()
        trade_svc = _require_service(app, 'trade_engine')
        offer_list = [i.strip() for i in offer_ids.split(",") if i.strip()] if offer_ids else []
        request_list = [i.strip() for i in request_ids.split(",") if i.strip()] if request_ids else []
        offer = trade_svc.propose_trade("local", target_spark_id, offer_list, request_list)
        return {"status": "ok", "trade_id": offer.id}

    @app.post("/api/trade/accept")
    async def trade_accept(trade_id: str = Query(...)):
        container, db = check()
        trade_svc = _require_service(app, 'trade_engine')
        return trade_svc.accept_trade(trade_id)

    @app.post("/api/trade/reject")
    async def trade_reject(trade_id: str = Query(...)):
        container, db = check()
        trade_svc = _require_service(app, 'trade_engine')
        if trade_svc.reject_trade(trade_id):
            return {"status": "ok"}
        return {"status": "error", "message": "Trade not found"}

    @app.get("/api/trade/evaluate")
    async def trade_evaluate(trade_id: str = Query(...)):
        container, db = check()
        trade_svc = _require_service(app, 'trade_engine')
        result = trade_svc.evaluate_trade(trade_id)
        if not result:
            return {"status": "error", "message": "Trade not found"}
        return result

    @app.get("/api/trade/list")
    async def trade_list():
        container, db = check()
        trade_svc = _require_service(app, 'trade_engine')
        trades = trade_svc.get_active_trades()
        return {"trades": [
            {"id": t.id, "target": t.target_spark_id,
             "offer_ids": t.offer_knowledge_ids,
             "request_ids": t.request_knowledge_ids,
             "status": t.status, "created_at": t.created_at}
            for t in trades
        ]}
