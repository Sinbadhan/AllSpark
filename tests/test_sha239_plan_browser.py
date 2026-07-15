"""Real Chrome evidence for the accepted 24-hour plan on Dashboard."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from allspark.adapters.web_ui import create_app
from tests.assessment_helpers import valid_initial_assessment
from tests.test_sha196_browser import _Chrome, _chrome_binary
from tests.test_sha221_init_browser import _serve_init


def _post_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def test_accepted_primary_action_is_first_viewport_truth_on_desktop_and_mobile(
    tmp_path: Path,
) -> None:
    app = create_app(str(tmp_path / "plan-browser.db"))
    with _serve_init(app) as base_url:
        assessment = valid_initial_assessment(confirmed=False)
        preview = _post_json(
            f"{base_url}/api/init/assessment/preview",
            {"language": "en", "assessment": assessment},
        )
        assessment["as_of"] = preview["summary"]["as_of"]
        assessment["confirmed"] = True
        selected = preview["plan"]["primary_candidate_ids"][0]
        completed = _post_json(
            f"{base_url}/api/init/complete",
            {
                "language": "en",
                "assessment": assessment,
                "plan_id": preview["plan"]["id"],
                "primary_action_id": selected,
            },
        )
        assert completed["plan"]["accepted_action_id"] == selected

        with _Chrome(
            _chrome_binary(), tmp_path / "chrome-plan-profile"
        ) as browser:
            browser.call(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": 1280,
                    "height": 800,
                    "deviceScaleFactor": 1,
                    "mobile": False,
                },
            )
            browser.navigate(base_url)
            browser.wait_for(
                "!!document.querySelector('#primary-plan .primary-plan-title')"
            )
            desktop = browser.evaluate(
                """(() => {
                  const panel=document.getElementById('primary-plan');
                  const title=panel.querySelector('.primary-plan-title');
                  const icon=panel.querySelector('.material-symbols-outlined');
                  const rect=panel.getBoundingClientRect();
                  return {title:title.textContent,meta:panel.querySelectorAll('.primary-plan-meta>div').length,
                    iconHidden:icon.getAttribute('aria-hidden'),top:rect.top,bottom:rect.bottom,
                    overflow:document.documentElement.scrollWidth>window.innerWidth};
                })()"""
            )
            assert desktop["title"]
            assert desktop["meta"] == 4
            assert desktop["iconHidden"] == "true"
            assert 0 <= desktop["top"] < 800
            assert desktop["bottom"] <= 800
            assert desktop["overflow"] is False

            browser.call(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": 320,
                    "height": 760,
                    "deviceScaleFactor": 1,
                    "mobile": True,
                },
            )
            mobile = browser.evaluate(
                """(() => {
                  const panel=document.getElementById('primary-plan');
                  const reassess=panel.querySelector('.primary-plan-meta .primary-plan-risk');
                  const rect=panel.getBoundingClientRect();
                  return {left:rect.left,right:rect.right,width:rect.width,
                    overflow:document.documentElement.scrollWidth>window.innerWidth,
                    metaColumns:getComputedStyle(panel.querySelector('.primary-plan-meta')).gridTemplateColumns,
                    reassessTop:reassess.getBoundingClientRect().top,
                    beforeBriefing:Boolean(panel.compareDocumentPosition(document.getElementById('briefing-banner')) & Node.DOCUMENT_POSITION_FOLLOWING)};
                })()"""
            )
            assert mobile["left"] >= 0
            assert mobile["right"] <= 320
            assert mobile["width"] > 0
            assert mobile["overflow"] is False
            assert len(mobile["metaColumns"].split()) == 1
            assert mobile["reassessTop"] < 760
            assert mobile["beforeBriefing"] is True
