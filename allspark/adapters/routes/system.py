"""Platform-level system routes: language, mode, modules, about, task actions."""

from fastapi import HTTPException, Request

import allspark
from allspark.adapters.routes.helpers import (
    _get_service,
    _require_service,
    error_response,
    service_unavailable,
)
from allspark.core.i18n import get_language, set_language
from allspark.core.models import OperatingMode, PersonalityMode

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

    # ---------------- Language ----------------

    @app.post("/api/system/language")
    async def system_set_language(request: Request):
        container, db = check()
        body = await _safe_json(request)
        lang = (body.get("lang") or body.get("language") or "").strip().lower()
        if lang not in _VALID_LANGS:
            return error_response(
                "Invalid language",
                detail=f"'{lang}' is not supported.",
                next_action=f"Use one of: {sorted(_VALID_LANGS)}",
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
                "Mode required",
                detail="Body must contain {mode: '<personality-mode>'}.",
            )
        try:
            target = PersonalityMode(mode)
        except ValueError:
            return error_response(
                "Invalid personality mode",
                detail=f"'{mode}' is not a known personality mode.",
                next_action=f"Use one of: {[m.value for m in PersonalityMode]}",
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
                "Mode required",
                detail="Body must contain {mode: '<operating-mode>'}.",
            )
        try:
            target = OperatingMode(mode)
        except ValueError:
            return error_response(
                "Invalid operating mode",
                detail=f"'{mode}' is not a known operating mode.",
                next_action=f"Use one of: {[m.value for m in OperatingMode]}",
            )
        # Operating mode is persisted in operating_state via Database.
        from datetime import datetime as _dt

        state = db.get_operating_state()
        state.mode = target.value
        state.last_mode_change = _dt.now().isoformat()
        db.save_operating_state(state)
        return {"status": "ok", "mode": target.value}

    # ---------------- Modules enable/disable ----------------

    @app.post("/api/modules/{module_name}/enable")
    async def modules_enable(module_name: str):
        container, db = check()
        registry = _get_service(app, "registry")
        if registry is None:
            return service_unavailable("registry", app=app)
        try:
            ok = registry.enable(module_name)
        except Exception as e:
            return error_response("Enable failed", detail=str(e))
        return {"status": "ok" if ok else "error", "module": module_name, "enabled": True}

    @app.post("/api/modules/{module_name}/disable")
    async def modules_disable(module_name: str):
        container, db = check()
        registry = _get_service(app, "registry")
        if registry is None:
            return service_unavailable("registry", app=app)
        try:
            ok = registry.disable(module_name)
        except Exception as e:
            return error_response("Disable failed", detail=str(e))
        return {"status": "ok" if ok else "error", "module": module_name, "enabled": False}

    # ---------------- Tasks: start / complete / fail ----------------

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
            planner.start_task(task_id)
            return {"status": "ok", "task_id": task_id, "new_status": "in_progress"}
        if action == "complete":
            planner.complete_task(task_id)
            return {"status": "ok", "task_id": task_id, "new_status": "completed"}
        if action == "fail":
            planner.fail_task(task_id)
            return {"status": "ok", "task_id": task_id, "new_status": "failed"}
        raise HTTPException(400, f"Unknown action '{action}'. Use start | complete | fail.")


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
