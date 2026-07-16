"""Platform-level system routes: language, mode, modules, about, task actions."""

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

import allspark
from allspark.adapters.routes.helpers import (
    _get_service,
    _require_service,
    error_response,
    service_unavailable,
)
from allspark.core.i18n import get_language, set_language, t
from allspark.core.models import OperatingMode, PersonalityMode
from allspark.services.system_health import assess_system_health
from allspark.services.task_outcome import TaskOutcomeError

_VALID_LANGS = {"zh", "en"}


def register_system_routes(app, check):
    """Register platform/runtime endpoints used by the Web UI."""

    # ---------------- About / version ----------------

    @app.get("/api/system/about")
    async def system_about():
        container, db = check()
        flags = getattr(container.get("registry"), "flags", None) if container else None
        return {
            "name_zh": allspark.__name_zh__,
            "name_en": allspark.__name_en__,
            "version": allspark.__version__,
            "language": get_language(),
            "feature_flags": _flags_to_dict(flags),
            "license": "Apache-2.0",
            "homepage": "https://github.com/Sinbadhan/AllSpark",
        }

    # ---------------- Health / integrity (SHA-149) ----------------

    @app.get("/api/system/health")
    async def system_health():
        """Honest integrity score + state.

        Factors in core capabilities (LLM loaded, module support, warnings),
        not just error/warning count, so an unloaded LLM or unsupported
        modules never display 100% / "stable". State is one of
        healthy / degraded / unavailable (unknown is client-side, on fetch
        failure).
        """
        container, db = check()
        return assess_system_health(container)

    # ---------------- Language ----------------

    @app.post("/api/system/language")
    async def system_set_language(request: Request):
        container, db = check()
        body = await _safe_json(request)
        # Accept both "language" (canonical) and "lang" (shorthand).
        lang = (body.get("language") or body.get("lang") or "").strip().lower()
        if lang not in _VALID_LANGS:
            return error_response(
                t("error_invalid_language"),
                detail=t("error_lang_not_supported", lang=lang),
                next_action=t("error_lang_use_one_of", langs=", ".join(sorted(_VALID_LANGS))),
            )
        # set_language() persists to operating_state if a db_ref is set
        set_language(lang)
        return {"status": "ok", "language": lang}

    # ---------------- Personality mode ----------------

    @app.post("/api/system/personality")
    async def system_set_personality(request: Request):
        container, db = check()
        body = await _safe_json(request)
        mode = (body.get("mode") or "").strip().lower()
        if not mode:
            return error_response(
                t("error_mode_required"),
                detail=t("error_body_mode_personality"),
            )
        try:
            target = PersonalityMode(mode)
        except ValueError:
            return error_response(
                t("error_invalid_personality_mode"),
                detail=t("error_personality_mode_unknown", mode=mode),
                next_action=t("error_personality_use_one_of", modes=", ".join(m.value for m in PersonalityMode)),
            )
        personality = _require_service(app, "personality")
        new_mode = personality.set_mode(target)
        return {"status": "ok", "mode": getattr(new_mode, "value", str(new_mode))}

    # ---------------- Operating mode ----------------

    @app.post("/api/system/operating-mode")
    async def system_set_operating_mode(request: Request):
        container, db = check()
        body = await _safe_json(request)
        mode = (body.get("mode") or "").strip().lower()
        if not mode:
            return error_response(
                t("error_mode_required"),
                detail=t("error_body_mode_operating"),
            )
        try:
            target = OperatingMode(mode)
        except ValueError:
            return error_response(
                t("error_invalid_operating_mode"),
                detail=t("error_operating_mode_unknown", mode=mode),
                next_action=t("error_operating_use_one_of", modes=", ".join(m.value for m in OperatingMode)),
            )
        # Operating mode is persisted in operating_state via Database.
        from datetime import datetime as _dt

        state = db.get_operating_state()
        state.mode = target.value
        state.last_mode_change = _dt.now().isoformat()
        # Pin the mode so update_operating_mode() does not auto-revert it
        # on the next /api/status tick. Sending the same endpoint with a
        # body of {"mode": "...", "manual": false} clears the pin.
        manual = body.get("manual", True)
        state.mode_manual_override = bool(manual)
        db.save_operating_state(state)
        return {"status": "ok", "mode": target.value, "manual_override": state.mode_manual_override}

    # ---------------- Modules enable/disable ----------------

    @app.post("/api/modules/{module_name}/enable")
    async def modules_enable(module_name: str):
        container, db = check()
        registry = _get_service(app, "registry")
        if registry is None:
            return service_unavailable("registry", app=app)
        ok = registry.enable(module_name)
        if not ok:
            return error_response(
                t("error_module_not_found", name=module_name),
                detail=t("error_module_unsupported", name=module_name),
            )
        return {"status": "ok", "module": module_name, "enabled": True}

    @app.post("/api/modules/{module_name}/disable")
    async def modules_disable(module_name: str):
        container, db = check()
        registry = _get_service(app, "registry")
        if registry is None:
            return service_unavailable("registry", app=app)
        ok = registry.disable(module_name)
        if not ok:
            return error_response(
                t("error_module_not_found", name=module_name),
            )
        return {"status": "ok", "module": module_name, "enabled": False}

    # ---------------- Tasks: start / terminal outcome ----------------

    @app.post("/api/tasks/{task_id}/{action}")
    async def task_action(task_id: str, action: str, request: Request):
        container, db = check()
        action = action.strip().lower()
        engine = _get_service(app, "rule_engine")
        # rule_engine owns the planner via its `.planner` attribute.
        planner = getattr(engine, "planner", None) if engine else None
        if planner is None:
            planner = _get_service(app, "mission_planner")
        if planner is None:
            return service_unavailable("mission_planner", app=app)

        if action == "start":
            task = db.get_task(task_id)
            if task is None:
                raise HTTPException(404, t("error_task_not_found"))
            if task.status not in {"pending", "in_progress"}:
                raise HTTPException(409, t("error_task_already_terminal"))
            planner.start_task(task_id)
            return {"status": "ok", "task_id": task_id, "new_status": "in_progress"}
        terminal_status = {
            "complete": "completed",
            "fail": "failed",
            "skip": "skipped",
        }.get(action)
        if terminal_status is not None:
            body = await _safe_json(request)
            try:
                outcome = container.get("task_outcome").record(
                    task_id,
                    status=terminal_status,
                    result=body.get("result"),
                    evidence=body.get("evidence"),
                    resource_update=body.get("resource_update"),
                    confirm_resource_update=body.get(
                        "confirm_resource_update", False
                    ),
                )
            except TaskOutcomeError as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={
                        "status": "error",
                        "error": f"task_outcome_{exc.code}",
                        "detail": t(f"error_task_outcome_{exc.code}"),
                        "errors": [{"field": exc.field, "code": exc.code}],
                    },
                )
            action_loop = container.get("action_loop")
            survival_plan = container.get("survival_plan")
            return {
                "status": "ok",
                "task": action_loop.task_payload(outcome["task"]),
                "new_status": terminal_status,
                "resource_changed": outcome["resource_changed"],
                "plan_changed": outcome["plan_changed"],
                "plan": survival_plan.payload(outcome["plan"]),
                "next_task": (
                    action_loop.task_payload(outcome["next_task"])
                    if outcome["next_task"] is not None
                    else None
                ),
            }
        raise HTTPException(400, t("error_unknown_task_action", action=action))


# ---------------- helpers ----------------


async def _safe_json(request: Request) -> dict:
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


def _flags_to_dict(flags) -> dict:
    if flags is None:
        return {}
    out: dict[str, bool] = {}
    for attr in dir(flags):
        if attr.startswith("_"):
            continue
        try:
            val = getattr(flags, attr)
        except Exception:
            continue
        if isinstance(val, bool):
            out[attr] = val
    return out
