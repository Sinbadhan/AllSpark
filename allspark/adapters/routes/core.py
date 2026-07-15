"""Core API routes: status, resources, knowledge, chat, experience, llm, tasks, modules."""

import json
from typing import Any

from fastapi import HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from allspark.adapters.routes.helpers import _get_service, error_response
from allspark.core.i18n import render, set_language, t


class ChatRequest:
    def __init__(self, message: str, language: str = None):
        self.message = message
        self.language = language


class ExperienceRequest:
    def __init__(self, event: str, outcome: str, lesson: str = ""):
        self.event = event
        self.outcome = outcome
        self.lesson = lesson


class ResourceUpdateRequest:
    def __init__(self, type: str, amount: float):
        self.type = type
        self.amount = amount


def _resource_payload(resource_mgr, r):
    configured = resource_mgr.is_configured(r)
    remaining_status = resource_mgr.remaining_status(r)
    has_estimate = remaining_status == "finite"
    return {
        "type": r.type.value,
        "amount": r.current_amount,
        "unit": r.unit,
        "unit_label": t(f"resource_unit_{r.type.value}"),
        "daily_consumption": r.daily_consumption,
        "daily_intake": r.daily_intake,
        "amount_known": r.amount_known,
        "consumption_known": r.consumption_known,
        "intake_known": r.intake_known,
        "capacity": r.capacity,
        "capacity_known": r.capacity_known,
        "source": r.source,
        "source_label": t(f"resource_source_{r.source}"),
        "as_of": r.as_of,
        "last_updated": r.last_updated,
        "people_count": r.people_count,
        "amount_per_person": (
            r.current_amount / r.people_count if r.amount_known and r.people_count else None
        ),
        "remaining_hours_per_person": (
            r.estimated_remaining_hours if has_estimate and r.people_count else None
        ),
        "remaining_hours": r.estimated_remaining_hours if has_estimate else None,
        "remaining_status": remaining_status,
        "configured": configured,
        "offline": not configured,
        "status": "configured" if configured else "unconfigured",
    }


def register_core_routes(app, check):
    @app.get("/api/status")
    async def get_status():
        container, db = check()
        assessment = container.get("survival_engine").assess()
        resource_mgr = container.get("resource_manager")
        mode, _ = resource_mgr.update_operating_mode()
        warnings = resource_mgr.check_warnings()
        resources = resource_mgr.get_all_resources()
        exp_stats = container.get("experience").get_stats()
        llm_status = container.get("llm").get_status()

        return {
            "phase": assessment["phase"],
            "phase_name": assessment.get("phase_name", ""),
            "mode": mode.value if hasattr(mode, "value") else str(mode),
            "warnings": warnings,
            "resources": [_resource_payload(resource_mgr, r) for r in resources],
            "experience": exp_stats,
            "llm": llm_status,
            "modules": container.get("registry").format_status_dict(),
        }

    @app.get("/api/resources")
    async def get_resources():
        container, db = check()
        resource_mgr = container.get("resource_manager")
        resources = resource_mgr.get_all_resources()
        return [_resource_payload(resource_mgr, r) for r in resources]

    @app.post("/api/resources")
    async def update_resource(request: Request, type: str = Query(None), amount: float = Query(None)):
        container, db = check()
        consumption = None
        intake = None
        source = "user_input"
        people_count = 1
        as_of = None
        unknown = False
        amount_known = None
        consumption_known = None
        intake_known = None
        confirm_outlier = False
        capacity = None
        capacity_known = None
        data: dict[str, Any] = {}
        input_kind = "observed"
        if type is None or amount is None:
            data = await request.json()
            type = data.get("type", type)
            amount = data.get("amount", amount)
            consumption = data.get("daily_consumption", None)
            intake = data.get("daily_intake", None)
            people_count = data.get("people_count", people_count)
            as_of = data.get("as_of", None)
            unknown = data.get("unknown", False) is True
            amount_known = data.get("amount_known", None)
            consumption_known = data.get("consumption_known", None)
            intake_known = data.get("intake_known", None)
            confirm_outlier = data.get("confirm_outlier", False)
            capacity = data.get("capacity", None)
            capacity_known = data.get("capacity_known", None)
            input_kind = data.get("input_kind", "observed")
        from allspark.core.models import ResourceType
        from allspark.services.resource_manager import ResourceValidationError
        try:
            rtype = ResourceType(type)
        except (TypeError, ValueError):
            raise HTTPException(400, t("error_invalid_resource_type", type=type))
        kwargs: dict[str, Any] = {}
        try:
            resource_mgr = container.get("resource_manager")
            if "source" in data:
                raise ResourceValidationError("source", "source_controlled")
            if not isinstance(input_kind, str) or input_kind not in {"observed", "estimate"}:
                raise ResourceValidationError("input_kind", "invalid_input_kind")
            source = "estimate" if input_kind == "estimate" else "user_input"
            if unknown:
                resource_mgr.mark_unknown(
                    rtype,
                    source=source,
                    people_count=people_count,
                    as_of=as_of,
                )
                return {"status": "ok", "resource_status": "unknown"}
            if consumption is not None:
                kwargs["consumption"] = consumption
            if intake is not None:
                kwargs["intake"] = intake
            resource_mgr.update_resource(
                rtype,
                amount,
                **kwargs,
                source=source,
                people_count=people_count,
                as_of=as_of,
                amount_known=amount_known,
                consumption_known=consumption_known,
                intake_known=intake_known,
                capacity=capacity,
                capacity_known=capacity_known,
                confirm_outlier=confirm_outlier,
            )
        except (TypeError, ValueError, ResourceValidationError) as exc:
            if isinstance(exc, ResourceValidationError):
                detail = t(f"error_resource_{exc.reason}", field=exc.field)
            else:
                detail = t("error_resource_not_numeric", field="amount")
            raise HTTPException(422, detail) from exc
        return {"status": "ok"}

    @app.get("/api/knowledge/search")
    async def search_knowledge(q: str = Query(..., min_length=1), limit: int = 10):
        container, db = check()
        if container.get("knowledge"):
            entries = container.get("knowledge").search_by_language(q, limit)
            return [
                {
                    "id": e.id,
                    "category": e.category,
                    "subcategory": e.subcategory,
                    "priority": e.priority,
                    "title": e.title,
                    "summary": e.summary,
                    "steps": e.steps,
                    "warnings": e.warnings,
                    "verification": e.verification,
                    "source": e.source,
                }
                for e in entries
            ]
        return []

    @app.get("/api/knowledge/categories")
    async def get_categories():
        container, db = check()
        if container.get("knowledge"):
            cats = container.get("knowledge").get_categories()
            result = []
            for cat in cats:
                subs = container.get("knowledge").get_subcategories(cat)
                result.append({"category": cat, "subcategories": subs})
            return result
        return []

    @app.get("/api/knowledge/category/{category}")
    async def get_by_category(category: str, subcategory: str = ""):
        container, db = check()
        if container.get("knowledge"):
            cats = container.get("knowledge").get_categories()
            if category not in cats:
                raise HTTPException(404, f"Unknown category: '{category}'")
            entries = container.get("knowledge").get_by_category(category, subcategory)
            return [
                {
                    "id": e.id,
                    "title": e.title,
                    "summary": e.summary,
                    "priority": e.priority,
                    "category": e.category,
                    "subcategory": e.subcategory,
                    "verification": e.verification,
                    "language": e.language,
                }
                for e in entries
            ]
        return []

    # Knowledge IDs intentionally contain slashes (for example
    # survival/water/purification/boiling), so the route must consume the full
    # remaining path after the browser URL-encodes the ID.
    @app.get("/api/knowledge/{kid:path}")
    async def get_knowledge_entry(kid: str):
        container, db = check()
        entry = db.get_knowledge(kid)
        if not entry:
            raise HTTPException(404, "Knowledge entry not found")
        return {
            "id": entry.id,
            "category": entry.category,
            "subcategory": entry.subcategory,
            "priority": entry.priority,
            "title": entry.title,
            "summary": entry.summary,
            "steps": entry.steps,
            "prerequisites": entry.prerequisites,
            "warnings": entry.warnings,
            "verification": entry.verification,
            "source": entry.source,
            "language": entry.language,
        }

    @app.post("/api/chat")
    async def chat(request: Request, message: str = Query(None), language: str = None):
        container, db = check()
        if message is None:
            data = await request.json()
            message = data.get("message", "")
            language = data.get("language", language)
        if language:
            set_language(language)
        response = container.get("rule_engine").process_input(message)
        return {"response": response}

    @app.post("/api/chat/stream")
    async def chat_stream(request: Request, message: str = Query(None), language: str = None):
        container, db = check()
        if message is None:
            data = await request.json()
            message = data.get("message", "")
            language = data.get("language", language)
        if language:
            set_language(language)

        llm = _get_service(app, "llm")
        if not llm or not llm.available:
            return JSONResponse({"response": container.get("rule_engine").process_input(message)})

        survival = _get_service(app, "survival_engine")
        phase = 0
        if survival:
            phase = survival.assess().get("phase", 0)

        def event_generator():
            for token in llm.survival_chat_stream(message, phase=phase):
                yield f"data: {json.dumps({'token': token})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/experience")
    async def get_experiences(limit: int = 20):
        container, db = check()
        entries = container.get("experience").get_recent(limit)
        return [
            {
                "id": e.id,
                "timestamp": e.timestamp,
                "event": e.event,
                "outcome": e.outcome,
                "lesson": e.lesson,
                "promoted": bool(e.related_knowledge_id),
            }
            for e in entries
        ]

    @app.post("/api/experience")
    async def log_experience(
        request: Request,
        event: str = Query(None),
        outcome: str = Query(None),
        lesson: str = Query(""),
    ):
        container, db = check()
        # Fall back to JSON body when query params are absent. Body may be
        # missing, empty, or non-JSON — none of which should reach the DB.
        if event is None or outcome is None:
            try:
                data = await request.json()
            except Exception:
                data = {}
            if isinstance(data, dict):
                event = data.get("event", event)
                outcome = data.get("outcome", outcome)
                lesson = data.get("lesson", lesson)
        # Validate before hitting the NOT NULL constraint on experience_log.event
        # (regression: B-1 — wrong-shape body used to surface as a 500).
        missing = [k for k, v in (("event", event), ("outcome", outcome)) if not v]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=t("error_missing_required_fields", fields=", ".join(missing)),
            )
        entry = container.get("experience").log(event=event, outcome=outcome, lesson=lesson or "")
        return {"id": entry.id, "status": "ok"}

    @app.get("/api/experience/patterns")
    async def get_patterns():
        container, db = check()
        return container.get("experience").get_patterns()

    @app.get("/api/llm/status")
    async def get_llm_status():
        container, db = check()
        return container.get("llm").get_status()

    @app.post("/api/llm/load")
    async def load_llm():
        container, db = check()
        ok = container.get("llm").load()
        if ok:
            container.get("registry").register("llm", container.get("llm"))
            container.get("registry").save_to_db(db)
            return {"status": "ok", "model": container.get("llm").model_name}
        return error_response(t("error_llm_load_failed"), detail=container.get("llm").error or "")

    @app.get("/api/tasks")
    async def get_tasks():
        container, db = check()
        active = db.get_active_tasks()
        return [
            {
                "id": t.id,
                "phase": t.phase,
                "priority": t.priority,
                "title": render(t.title),
                "description": render(t.description),
                "status": t.status,
            }
            for t in active
        ]

    @app.get("/api/modules")
    async def get_modules():
        container, db = check()
        return container.get("registry").format_status_dict()
