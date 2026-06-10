"""Shared helpers for route modules."""

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


def error_response(
    error: str,
    *,
    status: int = 400,
    detail: str = "",
    next_action: str = "",
) -> dict:
    """Unified error payload: {status, error, detail, next_action}."""
    return {
        "status": "error",
        "error": error,
        "detail": detail,
        "next_action": next_action,
    }


def service_unavailable(name: str, app=None) -> dict:
    """Standard response when an optional service is not loaded."""
    reason = f"Service '{name}' is not loaded in the current configuration."
    next = f"Check module status via /api/modules, or enable the feature flag for '{name}'."

    # Try to get richer info from ModuleRegistry
    if app:
        registry = _get_service(app, "registry")
        if registry:
            mod_status = None
            for m in registry.format_status_dict():
                if m["name"] == name:
                    mod_status = m
                    break
            if mod_status:
                if mod_status.get("status") == "unsupported":
                    reason = f"Hardware does not support '{name}' (requires feature flag: {mod_status.get('feature_flag', 'unknown')})."
                    next = "This module requires higher hardware tier to run."
                elif mod_status.get("status") == "disabled":
                    reason = f"Module '{name}' has been manually disabled."
                    next = f"Re-enable '{name}' via /api/modules."
                elif mod_status.get("status") == "available":
                    reason = f"Module '{name}' is supported but not yet loaded."
                    next = "Try restarting AllSpark or trigger a service load."

    return error_response(
        error=f"{name} not available",
        detail=reason,
        next_action=next,
    )


async def http_exception_handler(request: Request, exc: HTTPException):
    """Convert all HTTPException to unified error format."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "error": str(exc.detail),
            "detail": "",
            "next_action": "",
        },
    )


def _require_init(app):
    def _check():
        if not app.state.initialized or not app.state.engine:
            raise HTTPException(503, "AllSpark not initialized. Complete setup first.")
        return app.state.container, app.state.db
    return _check


def _get_service(app, name: str):
    """Get a service from the container, or None if not available."""
    container = getattr(app.state, 'container', None)
    if container:
        return container.get(name)
    return None


def _require_service(app, name: str):
    """Get a service from the container, raise 503 if not available."""
    svc = _get_service(app, name)
    if svc is None:
        raise HTTPException(503, f"Service '{name}' not available")
    return svc
