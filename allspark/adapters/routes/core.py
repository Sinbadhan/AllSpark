"""Core API routes: status, resources, knowledge, chat, experience, llm, tasks, modules."""

import json

from fastapi import HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from allspark.adapters.routes.helpers import _get_service, error_response
from allspark.core.i18n import set_language


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
    has_estimate = resource_mgr.has_remaining_estimate(r)
    return {
        "type": r.type.value,
        "amount": r.current_amount,
        "unit": r.unit,
        "daily_consumption": r.daily_consumption,
        "daily_intake": r.daily_intake,
        "remaining_hours": r.estimated_remaining_hours if has_estimate else None,
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
        if type is None or amount is None:
            data = await request.json()
            type = data.get("type", type)
            amount = data.get("amount", amount)
            consumption = data.get("daily_consumption", None)
            intake = data.get("daily_intake", None)
        from allspark.core.models import ResourceType
        try:
            rtype = ResourceType(type)
        except ValueError:
            raise HTTPException(400, f"Invalid resource type: {type}")
        kwargs = {}
        if consumption is not None:
            kwargs["consumption"] = float(consumption)
        if intake is not None:
            kwargs["intake"] = float(intake)
        container.get("resource_manager").update_resource(rtype, float(amount), **kwargs)
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
            entries = container.get("knowledge").get_by_category(category, subcategory)
            return [
                {
                    "id": e.id,
                    "title": e.title,
                    "summary": e.summary,
                    "priority": e.priority,
                }
                for e in entries
            ]
        return []

    @app.get("/api/knowledge/{kid}")
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
                detail=f"Missing required field(s): {', '.join(missing)}. "
                       f"Body must contain {{event, outcome, lesson?}}.",
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
        return error_response("LLM load failed", detail=container.get("llm").error or "")

    @app.get("/api/tasks")
    async def get_tasks():
        container, db = check()
        active = db.get_active_tasks()
        return [
            {
                "id": t.id,
                "phase": t.phase,
                "priority": t.priority,
                "title": t.title,
                "description": t.description,
                "status": t.status,
            }
            for t in active
        ]

    @app.get("/api/modules")
    async def get_modules():
        container, db = check()
        return container.get("registry").format_status_dict()
