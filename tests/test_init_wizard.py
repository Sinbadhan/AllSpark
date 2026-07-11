"""SHA-151: critical-path tests for the init wizard (was 10% covered).

Covers the testable wizard building blocks: questionnaire loading, the
option/multi-select input helpers (with console.input mocked), and the
hardware-detect step that persists the profile + module registry. The
interactive run_init_wizard orchestrator remains partly covered (it chains
these), but these guard the bootstrap-critical paths.
"""
from types import SimpleNamespace

from allspark.adapters import init_wizard
from allspark.adapters.init_wizard import (
    _load_questionnaire,
    _select_multi,
    _select_option,
    _step_hardware_detect,
)
from allspark.core.database import Database
from allspark.infrastructure.hardware import HardwareTier


class TestLoadQuestionnaire:
    def test_loads_structured_questionnaire(self):
        q = _load_questionnaire()
        assert isinstance(q, dict)
        for key in ("location_types", "shelter_statuses", "threat_types",
                    "skill_categories", "urgency_levels", "health_statuses"):
            assert key in q, f"missing {key}"
        assert len(q["location_types"]) >= 6

    def test_options_carry_stable_key_and_label_key(self):
        q = _load_questionnaire()
        for opt in q["location_types"]:
            assert "key" in opt and "label_key" in opt


class TestSelectOption:
    @staticmethod
    def _mock_input(monkeypatch, values):
        it = iter(values)
        monkeypatch.setattr(init_wizard.console, "input", lambda *a, **k: next(it))

    def test_valid_choice_returns_key(self, monkeypatch):
        self._mock_input(monkeypatch, ["1"])
        opts = [{"key": "a", "label_key": "q_a"}, {"key": "b", "label_key": "q_b"}]
        assert _select_option("pick", opts) == "a"

    def test_invalid_then_valid(self, monkeypatch):
        self._mock_input(monkeypatch, ["9", "2"])
        opts = [{"key": "a", "label_key": "q_a"}, {"key": "b", "label_key": "q_b"}]
        assert _select_option("pick", opts) == "b"

    def test_skip_returns_custom(self, monkeypatch):
        self._mock_input(monkeypatch, ["0", "my-custom"])
        opts = [{"key": "a", "label_key": "q_a"}]
        assert _select_option("pick", opts, allow_skip=True) == "my-custom"

    def test_empty_options_free_text(self, monkeypatch):
        self._mock_input(monkeypatch, ["free-text"])
        assert _select_option("pick", []) == "free-text"


class TestSelectMulti:
    def test_comma_separated_free_text(self, monkeypatch):
        monkeypatch.setattr(init_wizard.console, "input", lambda *a, **k: "a, b ,c")
        assert _select_multi("pick", []) == ["a", "b", "c"]


class TestStepHardwareDetect:
    def test_persists_profile_and_returns_flags(self, monkeypatch, tmp_path):
        fake = SimpleNamespace(
            tier=HardwareTier.MINIMUM, cpu_arch="x86_64", cpu_model="Test CPU",
            cpu_cores=4, ram_total_gb=8.0, ram_available_gb=6.0,
            storage_total_gb=100.0, storage_available_gb=50.0,
            gpu_info="none", gpu_available=False, os_name="Linux", os_version="5.0",
        )
        monkeypatch.setattr(init_wizard, "detect_hardware", lambda: fake)
        # No tier override -> stays MINIMUM (skips the override branch).
        monkeypatch.setattr(init_wizard, "_ask_tier_override", lambda tier: tier)

        db = Database(tmp_path / "hw.db")
        try:
            result = _step_hardware_detect(db)
            assert "profile" in result and "flags" in result
            profile = db.get_hardware_profile()
            assert profile["cpu_arch"] == "x86_64"
            assert profile["tier"] == "minimum"
            assert profile["cpu_cores"] == "4"
        finally:
            db.close()
