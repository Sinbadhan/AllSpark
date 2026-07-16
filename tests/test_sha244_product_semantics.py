"""SHA-244: focused navigation and one release/runtime truth model."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from allspark.core.i18n import get_language, set_language
from allspark.infrastructure.module_loader import (
    EXPERIMENTAL_MODULES,
    MODULE_DEFINITIONS,
    SUPPORTED_MODULES,
)
from allspark.services.system_health import SUPPORTED_CORE_SERVICES, assess_system_health
from tests.test_sha196_browser import _Chrome, _chrome_binary, _serve
from tests.test_web_ui_v11 import TempDb, _client


@pytest.fixture(autouse=True)
def _restore_process_language():
    original = get_language()
    yield
    set_language(original)


def test_about_modules_and_health_share_release_truth() -> None:
    with TempDb() as path:
        client = _client(path)
        about = client.get("/api/system/about").json()
        modules = client.get("/api/modules").json()
        health = client.get("/api/system/health").json()

        assert about["release"] == {
            "channel": "release_candidate",
            "stable": False,
            "supported_scope": "desktop_process_core_loop",
            "supported_runtime_mode": "process",
            "actual_runtime_mode": "process",
            "accessibility_supported": "macos_voiceover_core_web",
            "accessibility_testing": "windows_nvda",
            "support_groups": {
                "supported": [
                    "desktop_process_core_loop",
                    "macos_voiceover_core_web",
                ],
                "testing": ["windows_nvda"],
                "experimental": ["optional_capabilities"],
                "future": ["physical_transports_signing_governance"],
            },
        }
        assert about["capabilities"] == modules

        by_name = {module["name"]: module for module in modules}
        assert by_name["rule_engine"]["release_status"] == "supported"
        assert by_name["llm"]["release_status"] == "experimental"
        assert by_name["self_learning"]["release_status"] == "experimental"
        assert by_name["governance"]["release_status"] == "experimental"
        assert by_name["governance"]["runtime_state"] == "disabled"

        assert health["scope"] == "supported_core"
        assert health["score"] == 100
        assert health["state"] == "healthy"
        assert health["factors"]["llm_loaded"] is False
        assert health["factors"]["llm_status_known"] is True
        assert health["factors"]["modules_experimental"] > 0
        assert health["factors"]["experimental_active"] == 0
        assert health["factors"]["core_services_total"] == len(
            SUPPORTED_CORE_SERVICES
        )
        assert health["factors"]["core_services_operational"] == len(
            SUPPORTED_CORE_SERVICES
        )

        registry = client.app.state.container.get("registry")
        registry.flags.deploy_mode = "docker"
        docker_about = client.get("/api/system/about").json()
        assert docker_about["release"]["supported_runtime_mode"] == "process"
        assert docker_about["release"]["actual_runtime_mode"] == "docker"


def test_every_module_has_one_explicit_release_status() -> None:
    defined = {module.name for module in MODULE_DEFINITIONS}
    assert SUPPORTED_MODULES.isdisjoint(EXPERIMENTAL_MODULES)
    assert SUPPORTED_MODULES | EXPERIMENTAL_MODULES == defined


def test_system_decorative_icons_are_hidden_from_accessible_names() -> None:
    template = Path("allspark/templates/system.html").read_text(encoding="utf-8")
    spans = re.findall(
        r'<span class="material-symbols-outlined"[^>]*>', template
    )
    assert spans
    assert all('aria-hidden="true"' in span for span in spans)


def test_supported_failure_degrades_health_with_reason_impact_and_action() -> None:
    with TempDb() as path:
        client = _client(path)
        registry = client.app.state.container.get("registry")
        assert registry.disable("skf_manager") is True

        health = client.get("/api/system/health").json()
        assert health["score"] == 80
        assert health["state"] == "degraded"
        assert health["reasons"] == [{
            "code": "supported_capability_unavailable",
            "impact": "supported_workflow_at_risk",
            "action": "review_supported_capabilities",
            "capabilities": ["skf_manager"],
        }]


def test_missing_capability_registry_is_unavailable_not_healthy() -> None:
    class MissingRegistryContainer:
        def get(self, _name: str):
            return None

    health = assess_system_health(MissingRegistryContainer())  # type: ignore[arg-type]
    assert health["score"] == 0
    assert health["state"] == "unavailable"
    assert health["reasons"][0] == {
        "code": "capability_registry_unavailable",
        "impact": "core_loop_unverified",
        "action": "restart_and_review_logs",
        "capabilities": [],
    }
    expected_total = len(SUPPORTED_CORE_SERVICES) + len(SUPPORTED_MODULES)
    assert health["factors"]["supported_total"] == expected_total
    assert health["factors"]["supported_operational"] == 0
    assert health["factors"]["supported_unavailable"] == expected_total
    assert health["factors"]["core_services_total"] == len(
        SUPPORTED_CORE_SERVICES
    )
    assert health["factors"]["module_status_known"] is False


def test_missing_core_loop_services_fail_closed() -> None:
    with TempDb() as path:
        client = _client(path)
        container = client.app.state.container
        missing = {
            "resource_manager": "resource_tracking",
            "survival_engine": "phase_assessment",
            "survival_plan": "survival_decision",
            "mission_planner": "action_planning",
            "task_outcome": "outcome_reassessment",
            "initial_assessment": "initial_assessment",
        }
        for service in missing:
            container._services.pop(service)

        health = client.get("/api/system/health").json()
        assert health["score"] == 0
        assert health["state"] == "unavailable"
        assert health["reasons"] == [{
            "code": "supported_core_service_unavailable",
            "impact": "core_loop_unavailable",
            "action": "restart_and_review_logs",
            "capabilities": list(missing.values()),
        }]
        assert health["factors"]["core_services_operational"] == 2


def test_experimental_probe_failure_does_not_break_supported_health() -> None:
    class BrokenLLM:
        def get_status(self):
            raise RuntimeError("experimental runtime failed")

    with TempDb() as path:
        client = _client(path)
        client.app.state.container.register("llm", BrokenLLM())

        response = client.get("/api/system/health")
        health = response.json()
        assert response.status_code == 200
        assert health["score"] == 100
        assert health["state"] == "healthy"
        assert health["factors"]["llm_loaded"] is False
        assert health["factors"]["llm_status_known"] is False


def test_missing_experimental_service_is_unknown_without_degrading_health() -> None:
    with TempDb() as path:
        client = _client(path)
        client.app.state.container._services.pop("llm")

        health = client.get("/api/system/health").json()
        assert health["score"] == 100
        assert health["state"] == "healthy"
        assert health["factors"]["llm_loaded"] is False
        assert health["factors"]["llm_status_known"] is False


@pytest.mark.parametrize(
    "payload",
    [{}, {"loaded": "false"}, {"available": "false"}],
)
def test_malformed_experimental_status_is_unknown(payload) -> None:
    class MalformedLLM:
        def get_status(self):
            return payload

    with TempDb() as path:
        client = _client(path)
        client.app.state.container.register("llm", MalformedLLM())

        health = client.get("/api/system/health").json()
        assert health["score"] == 100
        assert health["state"] == "healthy"
        assert health["factors"]["llm_loaded"] is False
        assert health["factors"]["llm_status_known"] is False


def test_supported_probe_failure_returns_structured_unavailable() -> None:
    class BrokenResourceManager:
        def check_warnings(self):
            raise RuntimeError("resource probe failed")

    with TempDb() as path:
        client = _client(path)
        client.app.state.container.register(
            "resource_manager", BrokenResourceManager()
        )

        response = client.get("/api/system/health")
        health = response.json()
        assert response.status_code == 200
        assert health["score"] == 0
        assert health["state"] == "unavailable"
        assert health["reasons"] == [{
            "code": "supported_core_probe_failed",
            "impact": "core_loop_unverified",
            "action": "restart_and_review_logs",
            "capabilities": ["resource_tracking"],
        }]
        assert health["factors"]["situation_status_known"] is False


def test_registry_probe_failure_returns_structured_unavailable() -> None:
    class BrokenRegistry:
        def format_status_dict(self):
            raise RuntimeError("registry serialization failed")

    with TempDb() as path:
        client = _client(path)
        client.app.state.container.register("registry", BrokenRegistry())

        response = client.get("/api/system/health")
        health = response.json()
        assert response.status_code == 200
        assert health["score"] == 0
        assert health["state"] == "unavailable"
        assert health["reasons"][0]["code"] == "capability_registry_unavailable"
        assert health["factors"]["supported_total"] == (
            len(SUPPORTED_CORE_SERVICES) + len(SUPPORTED_MODULES)
        )
        assert health["factors"]["supported_operational"] == 0


def test_registry_acquisition_failure_returns_structured_unavailable() -> None:
    class BrokenContainer:
        def get(self, name):
            assert name == "registry"
            raise RuntimeError("registry acquisition failed")

    health = assess_system_health(BrokenContainer())  # type: ignore[arg-type]
    assert health["score"] == 0
    assert health["state"] == "unavailable"
    assert health["reasons"][0]["code"] == "capability_registry_unavailable"


@pytest.mark.parametrize("payload", [None, ["not-a-module"], [{}]])
def test_invalid_registry_payload_returns_structured_unavailable(payload) -> None:
    class InvalidRegistry:
        def format_status_dict(self):
            return payload

    with TempDb() as path:
        client = _client(path)
        client.app.state.container.register("registry", InvalidRegistry())
        response = client.get("/api/system/health")
        assert response.status_code == 200
        assert response.json()["state"] == "unavailable"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("is_core", False),
        ("feature_flag", "forged"),
        ("description_en", "forged"),
        ("dependency_installed", "yes"),
        ("running", True),
    ],
)
def test_forged_module_contract_fails_closed(field, value) -> None:
    with TempDb() as path:
        client = _client(path)
        modules = client.get("/api/modules").json()
        rule_engine = next(
            module for module in modules if module["name"] == "rule_engine"
        )
        rule_engine[field] = value

        class ForgedRegistry:
            def format_status_dict(self):
                return modules

        client.app.state.container.register("registry", ForgedRegistry())
        health = client.get("/api/system/health").json()
        assert health["score"] == 0
        assert health["state"] == "unavailable"
        assert health["factors"]["module_status_known"] is False


@pytest.mark.parametrize(
    "changes",
    [
        {"dependency_installed": False},
        {"hardware_capable": False},
        {"configured": False},
        {"status": "disabled"},
    ],
)
def test_contradictory_module_state_fails_closed(changes) -> None:
    with TempDb() as path:
        client = _client(path)
        modules = client.get("/api/modules").json()
        rule_engine = next(
            module for module in modules if module["name"] == "rule_engine"
        )
        rule_engine.update(changes)

        class ContradictoryRegistry:
            def format_status_dict(self):
                return modules

        client.app.state.container.register(
            "registry", ContradictoryRegistry()
        )
        health = client.get("/api/system/health").json()
        assert health["score"] == 0
        assert health["state"] == "unavailable"
        assert health["factors"]["module_status_known"] is False


def test_running_module_must_be_loaded() -> None:
    with TempDb() as path:
        client = _client(path)
        modules = client.get("/api/modules").json()
        rule_engine = next(
            module for module in modules if module["name"] == "rule_engine"
        )
        rule_engine.update({
            "status": "available",
            "running": True,
            "capability_state": "running",
            "runtime_state": "running",
        })

        class ContradictoryRegistry:
            def format_status_dict(self):
                return modules

        client.app.state.container.register(
            "registry", ContradictoryRegistry()
        )
        health = client.get("/api/system/health").json()
        assert health["score"] == 0
        assert health["state"] == "unavailable"
        assert health["factors"]["module_status_known"] is False


@pytest.mark.parametrize("payload", [None, ["not-a-warning"], [{}]])
def test_invalid_resource_probe_payload_is_isolated(payload) -> None:
    class InvalidResourceManager:
        def check_warnings(self):
            return payload

    with TempDb() as path:
        client = _client(path)
        client.app.state.container.register(
            "resource_manager", InvalidResourceManager()
        )
        response = client.get("/api/system/health")
        health = response.json()
        assert response.status_code == 200
        assert health["score"] == 0
        assert health["state"] == "unavailable"
        assert health["reasons"][0]["code"] == "supported_core_probe_failed"


def test_service_acquisition_failures_are_isolated() -> None:
    with TempDb() as path:
        client = _client(path)
        container = client.app.state.container
        original_get = container.get

        def failing_get(name):
            if name in {"task_outcome", "llm"}:
                raise RuntimeError(f"{name} acquisition failed")
            return original_get(name)

        container.get = failing_get
        response = client.get("/api/system/health")
        health = response.json()
        assert response.status_code == 200
        assert health["score"] == 0
        assert health["state"] == "unavailable"
        assert health["reasons"] == [{
            "code": "supported_core_probe_failed",
            "impact": "core_loop_unverified",
            "action": "restart_and_review_logs",
            "capabilities": ["outcome_reassessment"],
        }]
        assert health["factors"]["supported_operational"] == 21
        assert health["factors"]["supported_unavailable"] == 1
        assert health["factors"]["llm_status_known"] is False


@pytest.mark.parametrize(
    (
        "language",
        "primary",
        "management",
        "release_label",
        "healthy_label",
        "unknown_label",
    ),
    [
        (
            "en", ["Situation", "Actions", "Knowledge"], "Management",
            "Release Candidate", "Healthy", "Unknown",
        ),
        (
            "zh", ["状况", "行动", "知识"], "管理",
            "发布候选版", "健康", "未知",
        ),
    ],
)
def test_navigation_about_system_and_config_are_consistent_in_real_chrome(
    tmp_path: Path,
    language: str,
    primary: list[str],
    management: str,
    release_label: str,
    healthy_label: str,
    unknown_label: str,
) -> None:
    client = _client(str(tmp_path / f"sha244-{language}.db"))
    assert client.post(
        "/api/system/language", json={"language": language}
    ).status_code == 200

    with _serve(client.app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / f"chrome-profile-{language}"
    ) as browser:
        browser.call(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                  window.__sha244Errors = [];
                  addEventListener('error', event =>
                    window.__sha244Errors.push(String(event.error || event.message)));
                  addEventListener('unhandledrejection', event =>
                    window.__sha244Errors.push(String(event.reason)));
                """
            },
        )
        browser.navigate(base_url)
        shell = browser.evaluate(
            """(() => {
              const text = node => Array.from(node.childNodes)
                .filter(child => child.nodeType === Node.TEXT_NODE)
                .map(child => child.textContent.trim()).filter(Boolean).join(' ');
              return {
                links: Array.from(document.querySelectorAll('.sidebar nav a')).map(link => ({
                  href: new URL(link.href).pathname,
                  label: text(link),
                  current: link.getAttribute('aria-current'),
                })),
                sections: Array.from(document.querySelectorAll('.sidebar .nav-section-label'))
                  .map(node => node.textContent.trim()),
              };
            })()"""
        )
        assert [item["href"] for item in shell["links"]] == [
            "/", "/executions", "/repository", "/system", "/config"
        ]
        assert [item["label"] for item in shell["links"][:3]] == primary
        assert shell["links"][0]["current"] == "page"
        assert shell["sections"][1] == management

        browser.evaluate("document.getElementById('about-btn').click()")
        browser.wait_for(
            "document.getElementById('about-body').textContent.includes('Stable')"
        )
        about_text = browser.evaluate(
            "document.getElementById('about-body').textContent"
        )
        assert release_label in about_text
        for marker in ("Stable", "PROCESS", "NVDA"):
            assert marker in about_text

        stable_about = browser.evaluate(
            """(() => {
              closeAbout();
              const originalApi = window.api;
              window.api = (path, options) => path === '/api/system/about'
                ? originalApi(path, options).then(data => ({
                    ...data,
                    release: {...data.release, channel: 'stable', stable: true},
                  }))
                : originalApi(path, options);
              return openAbout().then(() => {
                const text = document.getElementById('about-body').textContent;
                window.api = originalApi;
                closeAbout();
                return text;
              });
            })()""",
            await_promise=True,
        )
        assert "Stable" in stable_about
        assert release_label not in stable_about

        browser.navigate(f"{base_url}/system")
        browser.evaluate("refreshSystem()", await_promise=True)
        system = browser.evaluate(
            """({
              errors: window.__sha244Errors,
              score: document.getElementById('integrity-value').textContent.trim(),
              status: document.getElementById('integrity-status').textContent.trim(),
              explanation: document.getElementById('health-explanation').textContent,
              table: document.getElementById('module-table').textContent,
              releaseBadges: Array.from(document.querySelectorAll('#module-table .release-badge'))
                .map(node => node.textContent.trim()),
              overflow: document.documentElement.scrollWidth > innerWidth,
            })"""
        )
        assert system["errors"] == []
        assert system["score"] == "100%"
        assert healthy_label in system["status"]
        assert system["explanation"].strip()
        assert system["overflow"] is False
        assert system["releaseBadges"]

        isolated = browser.evaluate(
            """(() => {
              const originalApi = window.api;
              window.api = (path, options) => path === '/api/init/hardware'
                ? Promise.resolve({
                    _http_error: true,
                    _http_status: 503,
                    error: 'hardware_detection_unavailable',
                  })
                : originalApi(path, options);
              return refreshSystem().then(() => {
                const result = {
                  score: document.getElementById('integrity-value').textContent.trim(),
                  hardware: document.getElementById('hw-detail').textContent.trim(),
                  modules: document.getElementById('module-table').textContent.trim(),
                };
                window.api = originalApi;
                return result;
              });
            })()""",
            await_promise=True,
        )
        assert isolated["score"] == "100%"
        assert isolated["hardware"] == unknown_label
        assert "undefined" not in isolated["hardware"]
        assert isolated["modules"]

        browser.navigate(f"{base_url}/config")
        browser.evaluate("initialConfigLoad", await_promise=True)
        config = browser.evaluate(
            """({
              errors: window.__sha244Errors,
              release: document.getElementById('cfg-release').textContent,
              scope: document.getElementById('cfg-scope').textContent,
              health: document.getElementById('cfg-health').textContent,
              llm: document.getElementById('cfg-llm').textContent,
              mode: document.getElementById('cfg-mode').textContent,
              capabilities: document.getElementById('cfg-capabilities').textContent,
              body: document.getElementById('config-grid').textContent,
              overflow: document.documentElement.scrollWidth > innerWidth,
            })"""
        )
        assert config["errors"] == []
        assert release_label in config["release"]
        assert "Stable" in config["release"]
        assert "PROCESS" in config["scope"]
        assert "100%" in config["health"] and healthy_label in config["health"]
        assert config["llm"]
        assert config["mode"] == "PROCESS"
        assert config["capabilities"]
        assert "recommended" not in config["body"].lower()
        assert "release_candidate" not in config["body"]
        assert "missing_dependency" not in config["body"]
        assert config["overflow"] is False

        stable_config = browser.evaluate(
            """(() => {
              const originalApi = window.api;
              window.api = (path, options) => path === '/api/system/about'
                ? originalApi(path, options).then(data => ({
                    ...data,
                    release: {...data.release, channel: 'stable', stable: true},
                  }))
                : originalApi(path, options);
              return loadConfig().then(() => {
                const text = document.getElementById('cfg-release').textContent;
                window.api = originalApi;
                return text;
              });
            })()""",
            await_promise=True,
        )
        assert stable_config.strip() == "Stable"
        assert release_label not in stable_config

        browser.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True},
        )
        browser.navigate(base_url)
        browser.evaluate("document.getElementById('mobile-nav-toggle').click()")
        browser.wait_for(
            "document.getElementById('mobile-nav').classList.contains('open')"
        )
        mobile = browser.evaluate(
            """({
              coreLinks: Array.from(document.querySelectorAll('#mobile-nav nav a'))
                .slice(0, 3).map(link => Array.from(link.childNodes)
                  .filter(child => child.nodeType === Node.TEXT_NODE)
                  .map(child => child.textContent.trim()).filter(Boolean).join(' ')),
              overflow: document.documentElement.scrollWidth > innerWidth,
            })"""
        )
        assert mobile["coreLinks"] == primary
        assert mobile["overflow"] is False
