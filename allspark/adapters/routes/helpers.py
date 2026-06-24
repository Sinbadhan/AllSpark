"""Shared helpers for route modules."""

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from allspark.core.i18n import t as _t


def error_response(
    error: str,
    *,
    status: int = 400,
    detail: str = "",
    next_action: str = "",
) -> JSONResponse:
    """Unified error payload: {status, error, detail, next_action}.

    Returns a JSONResponse with the correct HTTP status code (B-6).
    The ``error`` and ``detail`` strings are treated as literal text
    (callers should pass already-translated strings via ``t()``).
    """
    return JSONResponse(
        status_code=status,
        content={
            "status": "error",
            "error": error,
            "detail": detail,
            "next_action": next_action,
        },
    )


def service_unavailable(name: str, app=None) -> JSONResponse:
    """Standard response when an optional service is not loaded."""
    reason = _t("error_service_not_available", name=name)
    next_action = f"Check module status via /api/modules, or enable the feature flag for '{name}'."

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
                    reason = _t("error_module_unsupported", name=name)
                    next_action = "This module requires higher hardware tier to run."
                elif mod_status.get("status") == "disabled":
                    reason = _t("error_module_disabled", name=name)
                    next_action = f"Re-enable '{name}' via /api/modules."
                elif mod_status.get("status") == "available":
                    reason = _t("error_module_available", name=name)
                    next_action = "Try restarting AllSpark or trigger a service load."

    return error_response(
        error=f"{name} not available",
        detail=reason,
        next_action=next_action,
        status=503,
    )


async def http_exception_handler(request: Request, exc: Exception):
    """Convert all HTTPException to unified error format.

    Starlette types the handler's exception param as ``Exception`` (not
    ``HTTPException``), so we accept the broader type and narrow it here.
    """
    if isinstance(exc, HTTPException):
        status_code = exc.status_code
        detail = str(exc.detail)
    else:
        status_code = 500
        detail = str(exc)
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "error",
            "error": detail,
            "detail": "",
            "next_action": "",
        },
    )


def _require_init(app):
    def _check():
        if not app.state.initialized or not app.state.engine:
            raise HTTPException(503, _t("error_not_initialized"))
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
        raise HTTPException(503, _t("error_service_not_available", name=name))
    return svc
