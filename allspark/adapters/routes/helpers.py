"""Shared helpers for route modules."""

from fastapi import HTTPException


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
