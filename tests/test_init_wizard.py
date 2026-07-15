"""SHA-151: critical-path tests for the init wizard (was 10% covered).

Covers the testable wizard building blocks: questionnaire loading, the
option/multi-select input helpers (with console.input mocked), and the
hardware-detect step that persists the profile + module registry. The
interactive run_init_wizard orchestrator remains partly covered (it chains
these), but these guard the bootstrap-critical paths.
"""
from io import StringIO
from types import SimpleNamespace

from rich.console import Console

from allspark.adapters import init_wizard
from allspark.adapters.init_wizard import (
    _detect_initial_language,
    _load_questionnaire,
    _select_multi,
    _select_option,
    _step_hardware_detect,
    _step_initial_assessment,
)
from allspark.core.database import Database
from allspark.core.i18n import get_language, set_language
from allspark.core.models import ResourceType
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


class TestInitialLanguage:
    def test_zh_locale(self, monkeypatch):
        monkeypatch.setattr(init_wizard.locale, "getlocale", lambda: ("zh_CN", "UTF-8"))
        assert _detect_initial_language() == "zh"

    def test_en_locale(self, monkeypatch):
        monkeypatch.setattr(init_wizard.locale, "getlocale", lambda: ("en_US", "UTF-8"))
        assert _detect_initial_language() == "en"

    def test_unknown_or_unavailable_locale_falls_back_to_en(self, monkeypatch):
        monkeypatch.setattr(init_wizard.locale, "getlocale", lambda: ("fr_FR", "UTF-8"))
        assert _detect_initial_language() == "en"
        monkeypatch.setattr(init_wizard.locale, "getlocale", lambda: (None, None))
        assert _detect_initial_language() == "en"

    def test_locale_error_falls_back_to_en(self, monkeypatch):
        def fail():
            raise ValueError("locale unavailable")

        monkeypatch.setattr(init_wizard.locale, "getlocale", fail)
        assert _detect_initial_language() == "en"

    @staticmethod
    def _capture_choice(monkeypatch, locale_name, choices):
        output = StringIO()
        original_console = init_wizard.console
        original_language = get_language()
        values = iter(choices)
        captured = Console(file=output, force_terminal=False, width=100)
        monkeypatch.setattr(init_wizard.locale, "getlocale", lambda: (locale_name, "UTF-8"))
        monkeypatch.setattr(captured, "input", lambda *args, **kwargs: next(values))
        monkeypatch.setattr(init_wizard, "console", captured)
        try:
            result = init_wizard._step_language_select()
            return result, output.getvalue()
        finally:
            init_wizard.console = original_console
            set_language(original_language, persist=False)

    def test_zh_choice_screen_is_self_describing(self, monkeypatch):
        result, output = self._capture_choice(monkeypatch, "zh_CN", ["1"])
        assert result == "zh"
        assert "步骤 1/3：语言设置" in output
        assert "中文 / Chinese (zh)" in output
        assert "English / 英语 (en)" in output

    def test_unknown_locale_uses_english_copy_and_error(self, monkeypatch):
        result, output = self._capture_choice(monkeypatch, "fr_FR", ["bad", "2"])
        assert result == "en"
        assert "Step 1/3: Language" in output
        assert "Your system locale only sets the default" in output
        assert "Enter 1 or 2" in output


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


class TestAssessmentInputHelpers:
    @staticmethod
    def _inputs(monkeypatch, values):
        answers = iter(values)
        monkeypatch.setattr(init_wizard.console, "input", lambda *a, **k: next(answers))

    def test_explicit_state_retries_and_accepts_both_states(self, monkeypatch):
        self._inputs(monkeypatch, ["bad", "1"])
        assert init_wizard._explicit_known_state("People") == "known"
        self._inputs(monkeypatch, ["2"])
        assert init_wizard._explicit_known_state("People") == "unknown"

    def test_required_fact_retries_invalid_and_accepts_known_or_unknown(self, monkeypatch):
        options = [
            {"key": "healthy", "label_key": "q_health_healthy"},
            {"key": "minor", "label_key": "q_health_minor"},
        ]
        self._inputs(monkeypatch, ["bad", "9", "1"])
        assert init_wizard._required_fact("Health", options) == {
            "status": "known",
            "value": "healthy",
        }
        self._inputs(monkeypatch, ["3"])
        assert init_wizard._required_fact("Health", options) == {"status": "unknown"}

    def test_required_threats_covers_none_unknown_and_validated_selection(self, monkeypatch):
        options = [
            {"key": "flooding", "label_key": "q_threat_flooding"},
            {"key": "fire_risk", "label_key": "q_threat_fire_risk"},
        ]
        self._inputs(monkeypatch, ["bad", "1"])
        assert init_wizard._required_threats(options) == {"status": "none", "values": []}
        self._inputs(monkeypatch, ["3"])
        assert init_wizard._required_threats(options) == {"status": "unknown", "values": []}
        self._inputs(monkeypatch, ["2", "bad", "2", "9", "2", "1,1,2"])
        assert init_wizard._required_threats(options) == {
            "status": "selected",
            "values": ["flooding", "fire_risk"],
        }

    def test_resource_unknown_and_normal_known_paths(self, monkeypatch):
        self._inputs(monkeypatch, ["2", "1"])
        assert init_wizard._resource_assessment(ResourceType.WATER) == {
            "status": "unknown",
            "rates": {"status": "unknown"},
            "confirm_outlier": False,
        }
        self._inputs(monkeypatch, ["1", "10", "1"])
        assert init_wizard._resource_assessment(ResourceType.WATER) == {
            "status": "known",
            "amount": 10.0,
            "rates": {"status": "unknown"},
            "confirm_outlier": False,
        }

    def test_resource_retries_invalid_and_requires_outlier_confirmation(self, monkeypatch):
        self._inputs(
            monkeypatch,
            [
                "1", "", "100001", "n", "100001", "yes",
                "bad", "2", "", "2", "100001", "0", "n",
                "2", "100001", "0", "yes",
            ],
        )

        resource = init_wizard._resource_assessment(ResourceType.FIRE)

        assert resource == {
            "status": "known",
            "amount": 100001.0,
            "rates": {
                "status": "estimate",
                "basis": "group_total",
                "daily_consumption": 100001.0,
                "daily_intake": 0.0,
            },
            "confirm_outlier": True,
        }


class TestStepInitialAssessment:
    def test_known_people_count_requires_explicit_non_empty_value(self, monkeypatch):
        answers = iter(["", "2"])
        monkeypatch.setattr(init_wizard, "_explicit_known_state", lambda _label: "known")
        monkeypatch.setattr(init_wizard.console, "input", lambda *a, **k: next(answers))
        monkeypatch.setattr(
            init_wizard,
            "_required_fact",
            lambda *_args, **_kwargs: {"status": "unknown"},
        )
        monkeypatch.setattr(
            init_wizard,
            "_required_threats",
            lambda *_args, **_kwargs: {"status": "unknown", "values": []},
        )
        monkeypatch.setattr(
            init_wizard,
            "_resource_assessment",
            lambda *_args, **_kwargs: {
                "status": "unknown",
                "rates": {"status": "unknown"},
            },
        )

        assessment = _step_initial_assessment()

        assert assessment["people_count"] == {"status": "known", "value": 2}


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
