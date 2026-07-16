"""Shared system-health assessment for API and answer trust signals."""

from __future__ import annotations

import logging

from allspark.container import ServiceContainer
from allspark.infrastructure.module_loader import MODULE_DEFINITIONS, SUPPORTED_MODULES

logger = logging.getLogger(__name__)

SUPPORTED_CORE_SERVICES = {
    "resource_manager": "resource_tracking",
    "survival_engine": "phase_assessment",
    "survival_plan": "survival_decision",
    "mission_planner": "action_planning",
    "task_outcome": "outcome_reassessment",
    "initial_assessment": "initial_assessment",
    "action_loop": "confirmed_action_loop",
    "rule_engine": "workflow_orchestration",
}
MODULE_STATUS_VALUES = {"loaded", "available", "unsupported", "disabled"}
CAPABILITY_STATE_VALUES = {
    "disabled",
    "unsupported",
    "missing_dependency",
    "not_configured",
    "running",
    "ready",
}


def _valid_module_payload(modules: object) -> bool:
    if not isinstance(modules, list):
        return False
    definitions = {definition.name: definition for definition in MODULE_DEFINITIONS}
    expected_names = set(definitions)
    seen_names = set()
    for module in modules:
        if not isinstance(module, dict):
            return False
        name = module.get("name")
        if name not in expected_names or name in seen_names:
            return False
        seen_names.add(name)
        definition = definitions[name]
        expected_release = "supported" if name in SUPPORTED_MODULES else "experimental"
        if module.get("description_en") != definition.description_en:
            return False
        if module.get("description_zh") != definition.description_zh:
            return False
        if module.get("feature_flag") != definition.feature_flag:
            return False
        if module.get("is_core") is not definition.is_core:
            return False
        if module.get("release_status") != expected_release:
            return False
        if module.get("status") not in MODULE_STATUS_VALUES:
            return False
        if module.get("capability_state") not in CAPABILITY_STATE_VALUES:
            return False
        if module.get("runtime_state") != module.get("capability_state"):
            return False
        for field in (
            "hw_supported",
            "hardware_capable",
            "dependency_installed",
            "configured",
            "running",
            "experimental",
        ):
            if not isinstance(module.get(field), bool):
                return False
        expected_experimental = expected_release == "experimental"
        if module["experimental"] is not expected_experimental:
            return False
        if module["running"] and module["status"] != "loaded":
            return False
        if module["status"] == "disabled":
            expected_state = "disabled"
        elif not module["hardware_capable"]:
            expected_state = "unsupported"
        elif not module["dependency_installed"]:
            expected_state = "missing_dependency"
        elif not module["configured"]:
            expected_state = "not_configured"
        elif module["running"]:
            expected_state = "running"
        else:
            expected_state = "ready"
        if module["capability_state"] != expected_state:
            return False
    return seen_names == expected_names


def _valid_warning_payload(warnings: object) -> bool:
    if not isinstance(warnings, list):
        return False
    return all(
        isinstance(warning, dict)
        and isinstance(warning.get("resource"), str)
        and bool(warning["resource"].strip())
        and warning.get("level") in {"critical", "warning"}
        and isinstance(warning.get("message"), str)
        and bool(warning["message"].strip())
        for warning in warnings
    )


def _registry_unavailable_health() -> dict:
    supported_total = len(SUPPORTED_MODULES) + len(SUPPORTED_CORE_SERVICES)
    return {
        "score": 0,
        "state": "unavailable",
        "scope": "supported_core",
        "reasons": [{
            "code": "capability_registry_unavailable",
            "impact": "core_loop_unverified",
            "action": "restart_and_review_logs",
            "capabilities": [],
        }],
        "factors": {
            "llm_loaded": False,
            "llm_status_known": False,
            "modules_total": len(MODULE_DEFINITIONS),
            "module_status_known": False,
            "modules_loaded": 0,
            "modules_unsupported": 0,
            "modules_experimental": 0,
            "critical_count": 0,
            "warning_count": 0,
            "supported_total": supported_total,
            "supported_operational": 0,
            "supported_unavailable": supported_total,
            "experimental_active": 0,
            "core_services_total": len(SUPPORTED_CORE_SERVICES),
            "core_services_operational": 0,
            "situation_warning_count": 0,
            "situation_status_known": False,
        },
    }


def assess_system_health(container: ServiceContainer) -> dict:
    """Assess the supported product loop, not optional feature inventory.

    Runtime availability and release support are separate truths. Missing or
    idle Experimental capabilities must not make a healthy supported install
    look degraded, and survival-resource warnings belong to situation status.
    """
    try:
        registry = container.get("registry")
    except Exception:
        logger.warning("Capability registry acquisition failed", exc_info=True)
        return _registry_unavailable_health()
    if registry is None:
        return _registry_unavailable_health()
    try:
        modules = registry.format_status_dict()
        if not _valid_module_payload(modules):
            raise TypeError("Capability registry returned an invalid status payload")
    except Exception:
        logger.warning("Capability registry status probe failed", exc_info=True)
        return _registry_unavailable_health()

    missing_core_services = []
    core_probe_failures = []
    core_services = {}
    for service, capability in SUPPORTED_CORE_SERVICES.items():
        try:
            instance = container.get(service)
        except Exception:
            logger.warning(
                "Supported core service acquisition failed: %s",
                service,
                exc_info=True,
            )
            core_probe_failures.append(capability)
            instance = None
        else:
            if instance is None:
                missing_core_services.append(capability)
        core_services[service] = instance

    llm_status = {}
    llm_status_known = False
    try:
        llm = container.get("llm")
    except Exception:
        logger.warning("Experimental LLM acquisition failed", exc_info=True)
    else:
        if llm is not None:
            try:
                probed_status = llm.get_status()
                if (
                    isinstance(probed_status, dict)
                    and isinstance(probed_status.get("available"), bool)
                ):
                    llm_status = probed_status
                    llm_status_known = True
            except Exception:
                logger.warning("Experimental LLM status probe failed", exc_info=True)

    resource_mgr = core_services["resource_manager"]
    situation_status_known = resource_mgr is not None
    try:
        warnings = resource_mgr.check_warnings() if resource_mgr else []
        if not _valid_warning_payload(warnings):
            raise TypeError("Resource manager returned an invalid warning payload")
    except Exception:
        logger.warning("Supported resource status probe failed", exc_info=True)
        warnings = []
        core_probe_failures.append("resource_tracking")
        situation_status_known = False

    supported = [
        module for module in modules
        if module.get("release_status") == "supported"
    ]
    operational_states = {"running", "ready"}
    unavailable_supported = [
        module for module in supported
        if module.get("capability_state") not in operational_states
    ]
    unavailable_core = [
        module for module in unavailable_supported if module.get("is_core")
    ]
    experimental = [
        module for module in modules
        if module.get("release_status") == "experimental"
    ]
    experimental_active = [
        module for module in experimental
        if module.get("capability_state") == "running"
    ]

    score = (
        0
        if missing_core_services or core_probe_failures
        else max(0, 100 - (20 * len(unavailable_supported)))
    )
    if missing_core_services or core_probe_failures or unavailable_core:
        state = "unavailable"
    elif unavailable_supported:
        state = "degraded"
    else:
        state = "healthy"

    if missing_core_services:
        reasons = [{
            "code": "supported_core_service_unavailable",
            "impact": "core_loop_unavailable",
            "action": "restart_and_review_logs",
            "capabilities": missing_core_services,
        }]
    elif core_probe_failures:
        reasons = [{
            "code": "supported_core_probe_failed",
            "impact": "core_loop_unverified",
            "action": "restart_and_review_logs",
            "capabilities": core_probe_failures,
        }]
    elif unavailable_supported:
        reasons = [{
            "code": "supported_capability_unavailable",
            "impact": "supported_workflow_at_risk",
            "action": "review_supported_capabilities",
            "capabilities": [module["name"] for module in unavailable_supported],
        }]
    else:
        reasons = [{
            "code": "supported_core_operational",
            "impact": "core_loop_available",
            "action": "none",
            "capabilities": [],
        }]

    loaded = sum(1 for module in modules if module.get("status") == "loaded")
    unsupported = sum(1 for module in modules if module.get("status") == "unsupported")
    critical = sum(1 for warning in warnings if warning.get("level") == "critical")
    llm_loaded = llm_status.get("available") is True

    return {
        "score": score,
        "state": state,
        "scope": "supported_core",
        "reasons": reasons,
        "factors": {
            "llm_loaded": llm_loaded,
            "llm_status_known": llm_status_known,
            "modules_total": len(modules),
            "module_status_known": True,
            "modules_loaded": loaded,
            "modules_unsupported": unsupported,
            "modules_experimental": len(experimental),
            "critical_count": critical,
            "warning_count": len(warnings),
            "supported_total": len(supported) + len(SUPPORTED_CORE_SERVICES),
            "supported_operational": (
                len(supported)
                - len(unavailable_supported)
                + len(SUPPORTED_CORE_SERVICES)
                - len(missing_core_services)
                - len(core_probe_failures)
            ),
            "supported_unavailable": (
                len(unavailable_supported)
                + len(missing_core_services)
                + len(core_probe_failures)
            ),
            "core_services_total": len(SUPPORTED_CORE_SERVICES),
            "core_services_operational": (
                len(SUPPORTED_CORE_SERVICES)
                - len(missing_core_services)
                - len(core_probe_failures)
            ),
            "experimental_active": len(experimental_active),
            "situation_warning_count": len(warnings),
            "situation_status_known": situation_status_known,
        },
    }
