"""Shared system-health assessment for API and answer trust signals."""

from __future__ import annotations

from allspark.container import ServiceContainer


def assess_system_health(container: ServiceContainer) -> dict:
    registry = container.get("registry")
    modules = registry.format_status_dict() if registry else []
    llm = container.get("llm")
    llm_status = llm.get_status() if llm else {}
    resource_mgr = container.get("resource_manager")
    warnings = resource_mgr.check_warnings() if resource_mgr else []

    loaded = sum(1 for module in modules if module.get("status") == "loaded")
    unsupported = sum(
        1 for module in modules if module.get("status") == "unsupported"
    )
    experimental = sum(1 for module in modules if module.get("experimental"))
    critical = sum(1 for warning in warnings if warning.get("level") == "critical")
    llm_loaded = bool(llm_status.get("loaded"))

    score = 100
    if not llm_loaded:
        score -= 15
    if experimental:
        score -= 5
    score -= min(unsupported * 3, 15)
    score -= critical * 10
    score -= max(0, len(warnings) - critical) * 2
    score = max(0, min(100, score))

    degraded = (
        not llm_loaded
        or experimental > 0
        or critical > 0
        or unsupported > 0
        or bool(warnings)
    )
    if not degraded:
        state = "healthy"
    elif score >= 50:
        state = "degraded"
    else:
        state = "unavailable"

    return {
        "score": score,
        "state": state,
        "factors": {
            "llm_loaded": llm_loaded,
            "modules_total": len(modules),
            "modules_loaded": loaded,
            "modules_unsupported": unsupported,
            "modules_experimental": experimental,
            "critical_count": critical,
            "warning_count": len(warnings),
        },
    }
