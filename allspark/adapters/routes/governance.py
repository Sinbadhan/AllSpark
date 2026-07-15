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


def _governance_unavailable():
    return error_response(
        t("governance_access_unavailable"),
        status=503,
        detail=t("governance_access_unavailable_detail"),
        next_action=t("governance_access_unavailable_next"),
    )


def register_governance_routes(app, check):
    @app.get("/api/governance/status")
    async def governance_status():
        return _governance_unavailable()

    @app.post("/api/governance/member/add")
    async def governance_member_add(request: Request):
        return _governance_unavailable()

    @app.post("/api/governance/member/remove")
    async def governance_member_remove(request: Request):
        return _governance_unavailable()

    @app.post("/api/governance/member/role")
    async def governance_member_role(request: Request):
        return _governance_unavailable()

    @app.get("/api/governance/members")
    async def governance_members():
        return _governance_unavailable()

    @app.get("/api/governance/assess")
    async def governance_assess():
        return _governance_unavailable()

    @app.get("/api/governance/recommend")
    async def governance_recommend():
        return _governance_unavailable()

    @app.get("/api/governance/survival-value")
    async def governance_survival_value(member_id: str | None = Query(None)):
        return _governance_unavailable()

    @app.post("/api/governance/conflict/create")
    async def governance_conflict_create(request: Request):
        return _governance_unavailable()

    @app.post("/api/governance/conflict/mediate")
    async def governance_conflict_mediate(request: Request):
        return _governance_unavailable()

    @app.post("/api/governance/conflict/resolve")
    async def governance_conflict_resolve(request: Request):
        return _governance_unavailable()

    @app.get("/api/governance/conflicts")
    async def governance_conflicts():
        return _governance_unavailable()

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
                t("error_target_spark_id_required"),
                detail=t("error_body_target_spark_id"),
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
