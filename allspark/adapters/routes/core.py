"""Core API routes: status, resources, knowledge, chat, experience, llm, tasks, modules."""

import json
from typing import Any

from fastapi import HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from allspark.adapters.routes.helpers import _get_service, error_response
from allspark.core.i18n import set_language, t
from allspark.core.models import ResourceType


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
        "rate_basis": r.rate_basis,
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
        "people_count_known": r.people_count_known,
        "amount_per_person": (
            r.current_amount / r.people_count
            if r.amount_known and r.people_count_known and r.people_count
            else None
        ),
        "remaining_hours_per_person": (
            r.estimated_remaining_hours
            if has_estimate and r.people_count_known and r.people_count
            else None
        ),
        "remaining_hours": r.estimated_remaining_hours if has_estimate else None,
        "remaining_status": remaining_status,
        "configured": configured,
        "offline": not configured,
        "status": "configured" if configured else "unconfigured",
        "risk_status": resource_mgr.resource_risk_status(r),
    }


def register_core_routes(app, check):
    @app.get("/api/status")
    async def get_status():
        container, db = check()
        assessment = container.get("survival_engine").assess()
        resource_mgr = container.get("resource_manager")
        warnings = resource_mgr.check_warnings()
        resources = resource_mgr.get_all_resources()
        power = db.get_resource(ResourceType.POWER)
        operating_state = db.get_operating_state()
        mode_known = bool(
            operating_state.mode_manual_override
            or (
                power is not None
                and resource_mgr.is_configured(power)
                and resource_mgr.is_snapshot_current(power)
                and resource_mgr.has_complete_rate_data(power)
            )
        )
        mode = None
        if mode_known:
            mode, _ = resource_mgr.update_operating_mode()
        exp_stats = container.get("experience").get_stats()
        llm_status = container.get("llm").get_status()
        resource_payloads = [_resource_payload(resource_mgr, r) for r in resources]

        return {
            "phase": assessment["phase"],
            "phase_status": assessment["phase_status"],
            "phase_description": assessment["phase_description"],
            "missing_fields": assessment["missing_fields"],
            "stale_fields": assessment["stale_fields"],
            "mode": (
                mode.value if hasattr(mode, "value") else str(mode)
            ) if mode is not None else None,
            "mode_status": "known" if mode_known else "unknown",
            "warnings": warnings,
            "resources": resource_payloads,
            "configured_resource_count": sum(
                1 for resource in resource_payloads if resource["configured"]
            ),
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

    @app.get("/api/survival-plan")
    async def get_survival_plan():
        container, db = check()
        plan = db.get_survival_plan(active_only=True)
        if plan is None:
            return {"status": "unavailable", "reason": "no_active_plan"}
        service = container.get("survival_plan")
        return service.payload(plan)

    @app.post("/api/resources")
    async def update_resource(request: Request, type: str = Query(None), amount: float = Query(None)):
        container, db = check()
        consumption = None
        intake = None
        source = "user_input"
        people_count = 1
        people_count_known = True
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
            people_count_known = data.get("people_count_known", people_count_known)
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
            current_resource = db.get_resource(rtype)
            if "people_count_known" not in data:
                if "people_count" in data:
                    people_count_known = True
                elif current_resource is not None:
                    people_count = current_resource.people_count
                    people_count_known = current_resource.people_count_known
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
                    people_count_known=people_count_known,
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
                people_count_known=people_count_known,
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
            knowledge = container.get("knowledge")
            entries = knowledge.search_by_language(q, limit)
            return [knowledge.entry_payload(e, detail=False) for e in entries]
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
            knowledge = container.get("knowledge")
            entries = knowledge.get_by_category(category, subcategory)
            return [knowledge.entry_payload(e, detail=False) for e in entries]
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
        knowledge = container.get("knowledge")
        return knowledge.entry_payload(entry)

    @app.post("/api/chat")
    async def chat(
        request: Request,
        message: str = Query(None),
        language: str = None,
        conversation_id: str = None,
    ):
        container, db = check()
        if message is None:
            data = await request.json()
            message = data.get("message", "")
            language = data.get("language", language)
            conversation_id = data.get("conversation_id", conversation_id)
        if language:
            set_language(language)
        result = container.get("rule_engine").process_input_result(
            message,
            conversation_id=conversation_id,
        )
        assessment = container.get("survival_engine").assess()
        return {
            **result,
            "phase": assessment["phase"],
            "phase_status": assessment["phase_status"],
            "missing_fields": assessment["missing_fields"],
            "stale_fields": assessment["stale_fields"],
        }

    @app.post("/api/chat/stream")
    async def chat_stream(
        request: Request,
        message: str = Query(None),
        language: str = None,
        conversation_id: str = None,
    ):
        container, db = check()
        if message is None:
            data = await request.json()
            message = data.get("message", "")
            language = data.get("language", language)
            conversation_id = data.get("conversation_id", conversation_id)
        if language:
            set_language(language)

        rule_engine = container.get("rule_engine")
        safety_response = rule_engine.process_safety_input(
            message,
            conversation_id=conversation_id,
        )
        if safety_response is not None:
            return JSONResponse({"response": safety_response, "safety": True})
        action_loop = container.get("action_loop")
        if action_loop is not None:
            interaction = action_loop.process_chat(
                message,
                conversation_id=conversation_id,
            )
            if interaction is not None:
                return JSONResponse(
                    {
                        "response": interaction.response,
                        "interaction": interaction.metadata,
                    }
                )

        llm = _get_service(app, "llm")
        if not llm or not llm.available:
            return JSONResponse({
                "response": rule_engine.process_input(
                    message,
                    conversation_id=conversation_id,
                )
            })

        survival = _get_service(app, "survival_engine")
        assessment = None
        phase = None
        if survival:
            assessment = survival.assess()
            phase = assessment.get("phase")

        def event_generator():
            if assessment is not None:
                metadata = {
                    "phase": phase,
                    "phase_status": assessment["phase_status"],
                    "missing_fields": assessment["missing_fields"],
                    "stale_fields": assessment["stale_fields"],
                }
                yield f"event: phase\ndata: {json.dumps(metadata)}\n\n"
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
    async def get_tasks(
        limit: int = Query(200, ge=1, le=500),
        include_terminal: bool = Query(False),
    ):
        container, db = check()
        action_loop = container.get("action_loop")
        tasks = db.get_tasks(limit) if include_terminal else db.get_active_tasks()[:limit]
        return [action_loop.task_payload(task) for task in tasks]

    @app.post("/api/tasks/from-knowledge")
    async def create_task_from_knowledge(request: Request):
        container, db = check()
        try:
            data = await request.json()
        except Exception:
            data = {}
        knowledge_id = data.get("knowledge_id") if isinstance(data, dict) else None
        if not isinstance(knowledge_id, str) or not knowledge_id.strip():
            raise HTTPException(400, t("error_missing_required_fields", fields="knowledge_id"))
        result = container.get("action_loop").create_task_from_knowledge(
            knowledge_id.strip()
        )
        if result is None:
            raise HTTPException(404, t("error_knowledge_not_found"))
        task, created = result
        return JSONResponse(
            status_code=201 if created else 200,
            content={
                "created": created,
                "task": container.get("action_loop").task_payload(task),
            },
        )

    @app.post("/api/tasks/from-plan")
    async def create_task_from_plan():
        container, db = check()
        result = container.get("mission_planner").create_task_from_active_plan(
            container.get("survival_plan")
        )
        if result is None:
            raise HTTPException(409, t("error_active_plan_unavailable"))
        task, created = result
        return JSONResponse(
            status_code=201 if created else 200,
            content={
                "created": created,
                "task": container.get("action_loop").task_payload(task),
            },
        )

    @app.get("/api/modules")
    async def get_modules():
        container, db = check()
        return container.get("registry").format_status_dict()
