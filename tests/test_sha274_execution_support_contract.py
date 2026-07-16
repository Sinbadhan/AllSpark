"""SHA-274: Goals and Timeline use their exact API contracts in Execution Center."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_sha196_browser import _Chrome, _chrome_binary, _serve
from tests.test_sha213_csp_browser import _assert_clean, _install_probe
from tests.test_web_ui_v11 import _client


def _seed(client) -> tuple[str, str]:
    goal_response = client.post(
        "/api/goals/add",
        json={"title": "Secure water intake", "description": "Secure water intake"},
    )
    assert goal_response.status_code == 200, goal_response.text
    goal_id = goal_response.json()["goal"]["id"]
    client.app.state.db.update_goal_progress(goal_id, 0.5)
    timeline = client.app.state.container.get("timeline")
    event = timeline.record_system_event("Field checkpoint", "Water filter inspected")
    return goal_id, event["id"]


def _press_enter(browser: _Chrome) -> None:
    browser.call(
        "Input.dispatchKeyEvent",
        {
            "type": "keyDown",
            "key": "Enter",
            "code": "Enter",
            "text": "\r",
            "unmodifiedText": "\r",
            "windowsVirtualKeyCode": 13,
            "nativeVirtualKeyCode": 13,
        },
    )
    browser.call(
        "Input.dispatchKeyEvent",
        {
            "type": "keyUp",
            "key": "Enter",
            "code": "Enter",
            "windowsVirtualKeyCode": 13,
            "nativeVirtualKeyCode": 13,
        },
    )


def _open_tab_with_keyboard(browser: _Chrome, tab: str) -> None:
    browser.evaluate(f"document.querySelector('[data-exectab=\"{tab}\"]').focus()")
    assert browser.evaluate("document.activeElement.tagName") == "BUTTON"
    assert browser.evaluate("document.activeElement.dataset.exectab") == tab
    _press_enter(browser)
    browser.wait_for(
        f"document.getElementById('exectab-{tab}').style.display !== 'none'"
    )


def test_goals_and_timeline_api_contracts_are_structured(tmp_path: Path) -> None:
    client = _client(str(tmp_path / "contracts.db"))
    goal_id, event_id = _seed(client)

    goals = client.get("/api/goals")
    assert goals.status_code == 200
    assert set(goals.json()) == {"goals"}
    assert isinstance(goals.json()["goals"], list)
    goal = next(item for item in goals.json()["goals"] if item["id"] == goal_id)
    assert goal["progress"] == 0.5
    assert "phase" not in goal

    timeline = client.get("/api/timeline")
    assert timeline.status_code == 200
    assert set(timeline.json()) == {"events"}
    assert isinstance(timeline.json()["events"], list)
    event = next(item for item in timeline.json()["events"] if item["id"] == event_id)
    assert event["title"] == "Field checkpoint"
    assert event["description"] == "Water filter inspected"


@pytest.mark.parametrize(
    ("language", "active", "goals_empty", "goals_failed", "timeline_empty", "timeline_failed"),
    [
        ("zh", "进行中", "暂无目标", "无法加载目标", "暂无时间线事件", "无法加载时间线"),
        (
            "en",
            "Active",
            "No goals yet",
            "Unable to load goals",
            "No timeline events yet",
            "Unable to load the timeline",
        ),
    ],
)
def test_execution_support_tabs_render_truthfully_in_real_chrome(
    tmp_path: Path,
    language: str,
    active: str,
    goals_empty: str,
    goals_failed: str,
    timeline_empty: str,
    timeline_failed: str,
) -> None:
    client = _client(str(tmp_path / f"execution-{language}.db"))
    client.post("/api/system/language", json={"language": language})
    _seed(client)

    with _serve(client.app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / f"chrome-profile-{language}"
    ) as browser:
        _install_probe(browser)
        browser.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1280, "height": 844, "deviceScaleFactor": 1, "mobile": False},
        )
        browser.navigate(f"{base_url}/executions")

        _open_tab_with_keyboard(browser, "goals")
        browser.wait_for(
            "document.getElementById('goal-list').textContent.includes('Secure water intake')"
        )
        goal_text = browser.evaluate(
            "document.getElementById('goal-list').textContent.replace(/\\s+/g, ' ').trim()"
        )
        assert "Secure water intake" in goal_text
        assert active in goal_text
        assert "50%" in goal_text
        assert "0.5%" not in goal_text
        assert "undefined" not in goal_text

        goal_states = browser.evaluate(
            """(async () => {
              const originalApi = window.api;
              window.api = () => Promise.resolve({goals: []});
              await refreshGoals();
              const empty = document.getElementById('goal-list').textContent.trim();
              window.api = () => Promise.resolve({_http_error: true, _http_status: 500});
              await refreshGoals();
              const failed = document.getElementById('goal-list').textContent.trim();
              window.api = originalApi;
              await refreshGoals();
              return {empty, failed};
            })()""",
            await_promise=True,
        )
        assert goal_states["empty"] == goals_empty
        assert goals_failed in goal_states["failed"]

        _open_tab_with_keyboard(browser, "timeline")
        browser.wait_for(
            "document.getElementById('timeline-list').textContent.includes('Field checkpoint')"
        )
        timeline_text = browser.evaluate(
            "document.getElementById('timeline-list').textContent.replace(/\\s+/g, ' ').trim()"
        )
        assert "Field checkpoint" in timeline_text
        assert "Water filter inspected" in timeline_text
        assert "undefined" not in timeline_text

        timeline_states = browser.evaluate(
            """(async () => {
              const originalApi = window.api;
              window.api = () => Promise.resolve({events: []});
              await refreshTimeline();
              const empty = document.getElementById('timeline-list').textContent.trim();
              window.api = () => Promise.resolve({_http_error: true, _http_status: 500});
              await refreshTimeline();
              const failed = document.getElementById('timeline-list').textContent.trim();
              window.api = originalApi;
              await refreshTimeline();
              return {empty, failed};
            })()""",
            await_promise=True,
        )
        assert timeline_states["empty"] == timeline_empty
        assert timeline_failed in timeline_states["failed"]

        browser.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 320, "height": 844, "deviceScaleFactor": 1, "mobile": True},
        )
        layout = browser.evaluate(
            """({
              pageFits: document.documentElement.scrollWidth <= innerWidth + 1,
              tabFits: document.getElementById('exectab-timeline').scrollWidth <=
                document.getElementById('exectab-timeline').clientWidth + 1,
            })"""
        )
        assert layout == {"pageFits": True, "tabFits": True}
        _assert_clean(browser, f"Execution support contracts ({language})")


def test_execution_template_has_no_shape_guessing_fallbacks() -> None:
    source = Path("allspark/templates/executions.html").read_text(encoding="utf-8")
    assert "const goals = response.goals;" in source
    assert 'api("/api/timeline")' in source
    assert "data.events || data.timeline || data || []" not in source
    assert "GOAL_I18N.web_executions_empty" not in source
    assert "g.phase" not in source
