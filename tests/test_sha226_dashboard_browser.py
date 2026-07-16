"""SHA-226: Dashboard core state must fit narrow mobile viewports."""

from __future__ import annotations

from pathlib import Path

import pytest

from allspark.core.i18n import get_language, set_language
from tests.test_sha196_browser import _Chrome, _chrome_binary, _serve
from tests.test_web_ui_v11 import _client

_LAYOUT_STATE = """(() => {
  const main = document.querySelector('.main-content');
  const grid = document.querySelector('.bento-grid');
  const title = document.querySelector('.dash-header h1');
  const footer = document.querySelector('.footer');
  const mainRect = main.getBoundingClientRect();
  const footerRect = footer.getBoundingClientRect();
  const fits = element => {
    const rect = element.getBoundingClientRect();
    return rect.left >= mainRect.left - 1 && rect.right <= mainRect.right + 1;
  };
  const cards = Array.from(document.querySelectorAll('.resource-card'));
  return {
    viewport: innerWidth,
    pageFits: document.documentElement.scrollWidth <= innerWidth + 1,
    mainFits: main.scrollWidth <= main.clientWidth + 1,
    gridFits: grid.scrollWidth <= grid.clientWidth + 1,
    titleFits: fits(title) && title.scrollWidth <= title.clientWidth + 1,
    badgesFit: Array.from(document.querySelectorAll('.dash-badges .badge')).every(fits),
    footerFits: Array.from(footer.children).every(element => {
      const rect = element.getBoundingClientRect();
      return rect.left >= footerRect.left - 1 && rect.right <= footerRect.right + 1 &&
        rect.top >= footerRect.top - 1 && rect.bottom <= footerRect.bottom + 1;
    }),
    cardsFit: cards.length >= 5 && cards.every(card => {
      const header = card.querySelector('.card-header');
      const value = card.querySelector('.card-value');
      return fits(card) && card.scrollWidth <= card.clientWidth + 1 &&
        header.scrollWidth <= header.clientWidth + 1 && fits(value);
    }),
    statuses: cards.map(card => card.querySelector('.card-status').textContent.trim()),
  };
})()"""


def _assert_layout(state: dict, width: int) -> None:
    assert state["viewport"] == width
    for key in (
        "pageFits",
        "mainFits",
        "gridFits",
        "titleFits",
        "badgesFit",
        "footerFits",
        "cardsFit",
    ):
        assert state[key] is True, f"{width}px failed {key}: {state}"


@pytest.mark.parametrize("language", ["zh", "en"])
def test_dashboard_mobile_core_states_do_not_overflow(
    tmp_path: Path, language: str
) -> None:
    client = _client(str(tmp_path / f"dashboard-{language}.db"))
    client.post("/api/system/language", json={"language": language})

    with _serve(client.app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / f"chrome-profile-{language}"
    ) as browser:
        browser.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 430, "height": 844, "deviceScaleFactor": 1, "mobile": True},
        )
        browser.navigate(base_url)
        browser.wait_for("document.querySelectorAll('.resource-card').length >= 5")

        for width in (320, 360, 390, 430):
            browser.call(
                "Emulation.setDeviceMetricsOverride",
                {"width": width, "height": 844, "deviceScaleFactor": 1, "mobile": True},
            )
            _assert_layout(browser.evaluate(_LAYOUT_STATE), width)

        browser.evaluate(
            """(() => {
              const originalApi = window.api;
              window.api = async path => {
                if (path === '/api/status') return {
                  phase: 2,
                  phase_status: 'known',
                  mode: 'standard',
                  mode_status: 'known',
                  configured_resource_count: 5,
                  warnings: [],
                  resources: [
                    {type:'power', amount:123456789.25, unit:'kWh/day-equivalent-storage', remaining_hours:1, remaining_status:'finite', risk_status:'critical', configured:true},
                    {type:'water', amount:98765, unit:'litres-of-purified-water', remaining_hours:60, remaining_status:'finite', risk_status:'warning', configured:true},
                    {type:'food', amount:50, unit:'kg', remaining_hours:200, remaining_status:'finite', risk_status:'normal', configured:true},
                    {type:'fire', amount:8, unit:'hours-of-safe-combustion', remaining_hours:8, remaining_status:'finite', risk_status:'warning', configured:true},
                    {type:'storage', amount:4, unit:'long-term-containers', remaining_hours:null, remaining_status:'unknown', risk_status:'unknown', configured:true},
                  ],
                };
                if (path === '/api/tasks') return [];
                return originalApi(path);
              };
              return refreshDashboard().then(() => {
                document.querySelectorAll('.resource-card')[2]
                  .querySelector('.card-status').textContent = I18N.web_power_sustained;
              });
            })()""",
            await_promise=True,
        )

        for width in (320, 360, 390, 430):
            browser.call(
                "Emulation.setDeviceMetricsOverride",
                {"width": width, "height": 844, "deviceScaleFactor": 1, "mobile": True},
            )
            state = browser.evaluate(_LAYOUT_STATE)
            _assert_layout(state, width)
            assert any(
                marker in status
                for status in state["statuses"]
                for marker in ("CRITICAL", "危急")
            ), state["statuses"]
            assert I18N_POWER_SUSTAINED[language] in state["statuses"]


I18N_POWER_SUSTAINED = {"zh": "持续可用", "en": "Sustained"}


@pytest.fixture(autouse=True)
def _restore_process_language():
    original = get_language()
    yield
    set_language(original)
