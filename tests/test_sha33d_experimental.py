"""SHA-33d: unverified capabilities labeled Experimental in UI.

Modules not verified on real hardware (LLM/voice/Docker/sensors/GPS/power/
trade/psychology) must display an "EXP" badge in the System module table.
"""
from pathlib import Path


def _read(name: str) -> str:
    return (Path("allspark/templates") / name).read_text(encoding="utf-8")


class TestExperimentalLabeling:
    def test_experimental_set_defined(self):
        t = _read("system.html")
        assert "EXPERIMENTAL_MODULES" in t
        # Key unverified capabilities must be in the set.
        for mod in ("llm", "voice", "docker_manager", "sensor_hub"):
            assert f'"{mod}"' in t

    def test_exp_badge_rendered(self):
        t = _read("system.html")
        # SHA-33d: EXP badge appended for experimental modules.
        assert "EXPERIMENTAL_MODULES.has(m.name)" in t
        assert "EXP" in t

    def test_i18n_key_defined(self):
        for lang in ("zh", "en"):
            text = (Path(f"allspark/locales/{lang}.yaml")).read_text(encoding="utf-8")
            assert "web_system_experimental:" in text
