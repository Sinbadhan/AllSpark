"""SHA-225: hardware eligibility must not be presented as runtime availability."""

from __future__ import annotations

import json

from allspark.core.database import Database
from allspark.infrastructure.hardware import (
    FeatureFlags,
    HardwareProfile,
    HardwareTier,
    compute_feature_flags,
    format_hardware_report,
    resolve_runtime_deploy_mode,
)
from allspark.infrastructure.module_loader import ModuleRegistry
from tests.test_web_ui_v11 import TempDb, _client


def _profile() -> HardwareProfile:
    return HardwareProfile(
        tier=HardwareTier.RECOMMENDED,
        ram_total_gb=8,
        ram_available_gb=6,
        storage_total_gb=128,
        storage_available_gb=80,
        cpu_model="Test CPU",
        cpu_cores=8,
        cpu_arch="x86_64",
        os_name="Linux",
        os_version="test",
        gpu_info="None",
    )


def _capabilities(
    flags: FeatureFlags,
    *,
    dependency: bool,
    configured: bool,
    running: bool,
) -> list[dict]:
    registry = ModuleRegistry(flags)
    names = {item["name"] for item in registry.format_status_dict()}
    return registry.format_status_dict(
        dependency_overrides={name: dependency for name in names},
        configured_overrides={name: configured for name in names},
        running_overrides={name: running for name in names},
    )


def test_shared_capability_schema_separates_truth_dimensions() -> None:
    flags = compute_feature_flags(HardwareTier.RECOMMENDED)
    resolve_runtime_deploy_mode(flags, docker_available=False)
    modules = _capabilities(
        flags, dependency=False, configured=False, running=False
    )
    llm = next(item for item in modules if item["name"] == "llm")
    assert llm["hardware_capable"] is True
    assert llm["dependency_installed"] is False
    assert llm["configured"] is False
    assert llm["running"] is False
    assert llm["experimental"] is True
    assert llm["capability_state"] == "missing_dependency"


def test_no_docker_no_model_report_is_honest() -> None:
    flags = compute_feature_flags(HardwareTier.RECOMMENDED)
    resolve_runtime_deploy_mode(flags, docker_available=False)
    report = format_hardware_report(
        _profile(),
        flags,
        lang="en",
        capabilities=_capabilities(
            flags, dependency=False, configured=False, running=False
        ),
    )
    assert "Capability Preflight" in report
    assert "Feature Availability" not in report
    assert "Missing dependency" in report
    assert "Not configured" in report
    assert "Not running" in report
    assert "EXP" in report
    assert "Eligible target: Docker Mode" in report
    assert "Actual mode: Process Mode" in report
    assert "Docker daemon: Unavailable" in report
    assert "✅" not in report


def test_dependencies_present_but_unconfigured_are_not_available() -> None:
    flags = compute_feature_flags(HardwareTier.RECOMMENDED)
    resolve_runtime_deploy_mode(flags, docker_available=True)
    report = format_hardware_report(
        _profile(),
        flags,
        lang="en",
        capabilities=_capabilities(
            flags, dependency=True, configured=False, running=False
        ),
    )
    assert "Dependency installed" in report
    assert "Not configured" in report
    assert "Not running" in report
    assert "Feature Availability" not in report
    assert "✅" not in report


def test_complete_environment_reports_verified_runtime_state() -> None:
    flags = compute_feature_flags(HardwareTier.RECOMMENDED)
    resolve_runtime_deploy_mode(flags, docker_available=True)
    report = format_hardware_report(
        _profile(),
        flags,
        lang="en",
        capabilities=_capabilities(
            flags, dependency=True, configured=True, running=True
        ),
    )
    assert "Dependency installed" in report
    assert "Configured" in report
    assert "Running" in report
    assert "Docker daemon: Available" in report
    assert "Actual mode: Docker Mode" in report


def test_api_schema_contains_capability_truth() -> None:
    with TempDb() as path:
        modules = _client(path).get("/api/modules").json()
        assert modules
        for module in modules:
            assert {
                "hardware_capable",
                "dependency_installed",
                "configured",
                "running",
                "experimental",
                "capability_state",
                "runtime_state",
                "release_status",
            } <= module.keys()
        rule_engine = next(
            module for module in modules if module["name"] == "rule_engine"
        )
        assert rule_engine["running"] is False
        assert rule_engine["capability_state"] == "ready"


def test_system_page_consumes_capability_state() -> None:
    with TempDb() as path:
        html = _client(path).get("/system").text
        assert "m.capability_state" in html
        assert "m.release_status" in html
        assert "m.description_zh" in html
        assert "m.description_en" in html


def test_idle_runtime_is_configured_but_not_running() -> None:
    class IdleSensor:
        def get_status(self) -> dict:
            return {"polling": False}

    flags = FeatureFlags(sensor_hub=True)
    registry = ModuleRegistry(flags)
    assert registry.register("sensor_hub", IdleSensor()) is True
    sensor = next(
        item for item in registry.format_status_dict(
            dependency_overrides={"sensor_hub": True}
        )
        if item["name"] == "sensor_hub"
    )
    assert sensor["configured"] is True
    assert sensor["running"] is False
    assert sensor["capability_state"] == "ready"


def test_legacy_docker_flags_preserve_recommended_target(tmp_path) -> None:
    db = Database(tmp_path / "legacy.db")
    try:
        db.save_hardware_profile(
            "feature_flags",
            json.dumps({
                "deploy_mode": "docker",
                "docker_enabled": True,
                "docker_services": ["web"],
            }),
        )
        registry = ModuleRegistry.load_from_db(db)
        assert registry is not None
        assert registry.flags.recommended_deploy_mode == "docker"
        assert registry.flags.docker_eligible is True
        assert registry.flags.recommended_docker_services == ["web"]
    finally:
        db.close()
