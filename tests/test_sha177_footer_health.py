"""SHA-177: global footer status must match /api/system/health.

The footer previously read only /api/status warnings and showed "正常" even when
the System health card was degraded (LLM unloaded / unsupported modules). Now it
consults /api/system/health and reflects degraded/unavailable.
"""
from pathlib import Path


def _read(name: str) -> str:
    return (Path("allspark/templates") / name).read_text(encoding="utf-8")


class TestFooterHealthConsistency:
    def test_footer_reads_system_health(self):
        t = _read("base.html")
        # SHA-177: footer must consult /api/system/health, not just /api/status.
        assert "/api/system/health" in t

    def test_footer_maps_degraded_state(self):
        t = _read("base.html")
        assert 'state === "degraded"' in t
        assert "FOOTER_I18N.status_degraded" in t

    def test_footer_maps_unavailable_state(self):
        t = _read("base.html")
        assert 'state === "unavailable"' in t
        assert "FOOTER_I18N.status_unavailable" in t

    def test_footer_i18n_keys_defined(self):
        for lang in ("zh", "en"):
            text = (Path(f"allspark/locales/{lang}.yaml")).read_text(encoding="utf-8")
            assert "web_footer_status_degraded:" in text
            assert "web_footer_status_unavailable:" in text
