"""Governance and Trade API routes.

POST endpoints accept JSON body, matching the rest of the web API
(survival/system/etc.). GET endpoints keep query params per REST
convention. Regression: B-4 — the only POST that the Web UI ever calls
(`member/add`) used JSON body while the route declared `Query(...)`,
which silently 422'd and made the form do nothing.
"""

from fastapi import Query, Request

from allspark.adapters.routes.helpers import _require_service, error_response
from allspark.core.i18n import t


async def _safe_json(request: Request) -> dict:
    """Read the request body as a JSON dict, returning {} on any failure."""
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


def _split_csv(s: str | None) -> list[str]:
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


def register_governance_routes(app, check):
    @app.get("/api/governance/status")
    async def governance_status():
        container, db = check()
        gov_svc = _require_service(app, 'governance')
        return gov_svc.get_status()

    @app.post("/api/governance/member/add")
    async def governance_member_add(request: Request):
        container, db = check()
        gov_svc = _require_service(app, 'governance')
        body = await _safe_json(request)
        name = (body.get("name") or "").strip()
        if not name:
            return error_response(
                "Name required",
                detail="Body must contain {name: '<member-name>'}.",
            )
        role = (body.get("role") or "executor").strip()
        domains = body.get("domains") or []
        if isinstance(domains, str):
            domains = _split_csv(domains)
        member = gov_svc.add_member(name, role=role, domains=list(domains))
        return {"status": "ok", "member": {"id": member.id, "name": member.name, "role": member.role, "is_commander": member.is_commander}}

    @app.post("/api/governance/member/remove")
    async def governance_member_remove(request: Request):
        container, db = check()
        gov_svc = _require_service(app, 'governance')
        body = await _safe_json(request)
        member_id = (body.get("member_id") or "").strip()
        if not member_id:
            return error_response("member_id required",
                                  detail="Body must contain {member_id: '<id>'}.")
        if gov_svc.remove_member(member_id):
            return {"status": "ok"}
        return error_response(t("error_cannot_remove_member"), detail=t("error_member_not_found_detail", member_id=member_id))

    @app.post("/api/governance/member/role")
    async def governance_member_role(request: Request):
        container, db = check()
        gov_svc = _require_service(app, 'governance')
        body = await _safe_json(request)
        member_id = (body.get("member_id") or "").strip()
        role = (body.get("role") or "").strip()
        if not member_id or not role:
            return error_response(
                "member_id and role required",
                detail="Body must contain {member_id, role, domains?}.",
            )
        domains = body.get("domains")
        if isinstance(domains, str):
            domains = _split_csv(domains)
        if gov_svc.assign_role(member_id, role, list(domains) if domains is not None else None):
            return {"status": "ok"}
        return error_response(t("error_cannot_assign_role"), detail=t("error_invalid_member_or_role", member_id=member_id, role=role))

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
            return error_response(t("error_cannot_remove_member"), detail=t("error_member_not_found_detail", member_id=member_id))
        return result

    @app.post("/api/governance/conflict/create")
    async def governance_conflict_create(request: Request):
        container, db = check()
        gov_svc = _require_service(app, 'governance')
        body = await _safe_json(request)
        title = (body.get("title") or "").strip()
        parties_raw = body.get("parties")
        if not title or not parties_raw:
            return error_response(
                "title and parties required",
                detail="Body must contain {title, parties (list or comma-separated str)}.",
            )
        parties = parties_raw if isinstance(parties_raw, list) else _split_csv(parties_raw)
        conflict = gov_svc.create_conflict(title, body.get("description", ""), parties)
        return {"status": "ok", "conflict_id": conflict.id}

    @app.post("/api/governance/conflict/mediate")
    async def governance_conflict_mediate(request: Request):
        container, db = check()
        gov_svc = _require_service(app, 'governance')
        body = await _safe_json(request)
        conflict_id = (body.get("conflict_id") or "").strip()
        if not conflict_id:
            return error_response("conflict_id required",
                                  detail="Body must contain {conflict_id: '<id>'}.")
        result = gov_svc.mediate_conflict(conflict_id)
        if not result:
            return error_response(t("error_conflict_not_found"), detail=t("error_conflict_not_found_detail", conflict_id=conflict_id))
        return result

    @app.post("/api/governance/conflict/resolve")
    async def governance_conflict_resolve(request: Request):
        container, db = check()
        gov_svc = _require_service(app, 'governance')
        body = await _safe_json(request)
        conflict_id = (body.get("conflict_id") or "").strip()
        if not conflict_id:
            return error_response("conflict_id required",
                                  detail="Body must contain {conflict_id, resolution?}.")
        resolution = body.get("resolution") or "Resolved"
        if gov_svc.resolve_conflict(conflict_id, resolution):
            return {"status": "ok"}
        return error_response(t("error_cannot_resolve_conflict"), detail=t("error_conflict_not_found_detail", conflict_id=conflict_id))

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
    async def trade_propose(request: Request):
        container, db = check()
        trade_svc = _require_service(app, 'trade_engine')
        body = await _safe_json(request)
        target = (body.get("target_spark_id") or "").strip()
        if not target:
            return error_response(
                "target_spark_id required",
                detail="Body must contain {target_spark_id, offer_ids?, request_ids?}.",
            )
        offer_raw = body.get("offer_ids") or []
        request_raw = body.get("request_ids") or []
        offer_list = offer_raw if isinstance(offer_raw, list) else _split_csv(offer_raw)
        request_list = request_raw if isinstance(request_raw, list) else _split_csv(request_raw)
        offer = trade_svc.propose_trade("local", target, list(offer_list), list(request_list))
        return {"status": "ok", "trade_id": offer.id}

    @app.post("/api/trade/accept")
    async def trade_accept(request: Request):
        container, db = check()
        trade_svc = _require_service(app, 'trade_engine')
        body = await _safe_json(request)
        trade_id = (body.get("trade_id") or "").strip()
        if not trade_id:
            return error_response(t("error_trade_id_required"), detail=t("error_trade_id_format"))
        return trade_svc.accept_trade(trade_id)

    @app.post("/api/trade/reject")
    async def trade_reject(request: Request):
        container, db = check()
        trade_svc = _require_service(app, 'trade_engine')
        body = await _safe_json(request)
        trade_id = (body.get("trade_id") or "").strip()
        if not trade_id:
            return error_response(t("error_trade_id_required"), detail=t("error_trade_id_format"))
        if trade_svc.reject_trade(trade_id):
            return {"status": "ok"}
        return error_response(t("error_trade_not_found"), detail=t("error_trade_not_found_detail", trade_id=trade_id))

    @app.get("/api/trade/evaluate")
    async def trade_evaluate(trade_id: str = Query(...)):
        container, db = check()
        trade_svc = _require_service(app, 'trade_engine')
        result = trade_svc.evaluate_trade(trade_id)
        if not result:
            return error_response(t("error_trade_not_found"), detail=t("error_trade_not_found_detail", trade_id=trade_id))
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
