from pathlib import Path

import pytest

from allspark.adapters.web_ui import create_app
from allspark.core.database import Database
from allspark.core.i18n import set_language
from allspark.infrastructure.hardware import FeatureFlags
from allspark.infrastructure.module_loader import ModuleRegistry
from tests.test_sha196_browser import _Chrome, _chrome_binary, _serve


def _initialized_app(path: Path, language: str):
    db = Database(path)
    try:
        db.finalize_initialization(language)
        ModuleRegistry(FeatureFlags()).save_to_db(db)
    finally:
        db.close()
    return create_app(str(path))


@pytest.mark.parametrize(
    ("language", "locale", "pending", "footer_pending"),
    [
        ("en", "en-US", "Phase pending assessment", "Phase pending assessment"),
        ("zh", "zh-CN", "阶段待评估", "阶段待评估"),
    ],
)
def test_dashboard_phase_unknown_and_known_visual_truth(
    tmp_path: Path,
    request,
    language: str,
    locale: str,
    pending: str,
    footer_pending: str,
) -> None:
    request.addfinalizer(lambda: set_language("zh", persist=False))
    app = _initialized_app(tmp_path / f"phase-browser-{language}.db", language)
    with _serve(app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / "phase-chrome-profile"
    ) as browser:
        browser.call("Emulation.setLocaleOverride", {"locale": locale})
        browser.call(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": "Object.defineProperty(navigator, 'language', "
                f"{{get: () => '{locale}'}});"
            },
        )
        browser.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 320, "height": 568, "deviceScaleFactor": 1, "mobile": True},
        )
        browser.navigate(base_url)
        browser.wait_for(
            f"document.getElementById('phase-badge').textContent.includes({pending!r})"
        )
        unknown = browser.evaluate(
            """(() => {
              const badge = document.getElementById('phase-badge');
              const footer = document.getElementById('footer-resources');
              return {
                badge: badge.textContent.trim(),
                iconHidden: badge.querySelector('.material-symbols-outlined')?.getAttribute('aria-hidden'),
                success: badge.classList.contains('text-success'),
                footer: footer.textContent,
                overflow: document.documentElement.scrollWidth > window.innerWidth,
              };
            })()"""
        )
        assert unknown["badge"] == f"? {pending}"
        assert unknown["iconHidden"] == "true"
        assert unknown["success"] is False
        assert footer_pending in unknown["footer"]
        assert unknown["overflow"] is False
        assert "null" not in unknown["badge"].lower()
        assert "null" not in unknown["footer"].lower()

        for water_days, food_days, phase, expected_class in (
            (2.5, 20, 0, "text-critical"),
            (10, 6, 1, "text-critical"),
            (100, 100, 2, "text-warn"),
            (1000, 1000, 3, "text-success"),
            (2000, 1000, 4, "text-success"),
        ):
            state = browser.evaluate(
                f"""(async () => {{
                  for (const [type, amount] of [['water', {water_days}], ['food', {food_days}]]) {{
                    const response = await fetch('/api/resources', {{
                      method: 'POST', headers: {{'Content-Type': 'application/json'}},
                      body: JSON.stringify({{type, amount, daily_consumption: 1,
                        daily_intake: 0, input_kind: 'observed'}})
                    }});
                    if (!response.ok) throw new Error(await response.text());
                  }}
                  await refreshDashboard();
                  await updateFooter();
                  const badge = document.getElementById('phase-badge');
                  return {{
                    text: badge.textContent.trim(),
                    iconHidden: badge.querySelector('.material-symbols-outlined')?.getAttribute('aria-hidden'),
                    classes: badge.className,
                    footer: document.getElementById('footer-resources').textContent,
                  }};
                }})()""",
                await_promise=True,
            )
            assert state["text"].endswith(f"PHASE {phase}")
            assert expected_class in state["classes"]
            assert state["iconHidden"] == "true"
            assert str(phase) in state["footer"]
