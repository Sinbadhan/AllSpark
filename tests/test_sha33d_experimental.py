"""SHA-33d: unverified capabilities labeled Experimental in UI and CLI.

Modules not verified on real hardware (LLM/voice/Docker/sensors/GPS/power/
trade/psychology) must share one server-side release-status source.
"""
from pathlib import Path

from allspark.infrastructure.hardware import FeatureFlags
from allspark.infrastructure.module_loader import (
    EXPERIMENTAL_MODULES,
    ModuleRegistry,
)


def _read(name: str) -> str:
    return (Path("allspark/templates") / name).read_text(encoding="utf-8")


class TestExperimentalLabeling:
    def test_registry_is_single_source_and_contains_real_modules(self):
        registry = ModuleRegistry(FeatureFlags())
        names = {module["name"] for module in registry.format_status_dict()}
        for module in ("llm", "voice", "docker_manager", "sensor_hub"):
            assert module in EXPERIMENTAL_MODULES
            assert module in names

    def test_exp_badge_rendered(self):
        t = _read("system.html")
        assert "if (m.experimental)" in t
        assert "EXPERIMENTAL_MODULES" not in t
        assert "EXP" in t

    def test_cli_and_api_contract_expose_experimental_state(self):
        registry = ModuleRegistry(FeatureFlags())
        modules = registry.format_status_dict()
        assert all(isinstance(module["experimental"], bool) for module in modules)
        assert any(module["name"] == "docker_manager" and module["experimental"] for module in modules)
        assert "EXP" in registry.format_status(lang="en")

    def test_i18n_key_defined(self):
        for lang in ("zh", "en"):
            text = (Path(f"allspark/locales/{lang}.yaml")).read_text(encoding="utf-8")
            assert "web_system_experimental:" in text
            assert "module_experimental_short:" in text
