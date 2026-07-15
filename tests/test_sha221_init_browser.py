"""SHA-221: first-run language order and live bilingual questionnaire."""

from __future__ import annotations

import socket
import threading
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import uvicorn

from allspark.adapters.web_ui import create_app
from tests.test_sha196_browser import _Chrome, _chrome_binary


@contextmanager
def _serve_init(app):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", ws="none")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(200):
        try:
            urllib.request.urlopen(f"{url}/api/init/status", timeout=0.2)
            break
        except OSError:
            time.sleep(0.05)
    try:
        yield url
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_action_first_assessment_preview_switches_live_without_publishing(tmp_path: Path) -> None:
    app = create_app(str(tmp_path / "init.db"))
    with _serve_init(app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / "chrome-profile"
    ) as browser:
        browser.call("Emulation.setLocaleOverride", {"locale": "en-US"})
        browser.call(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": "Object.defineProperty(navigator, 'language', "
                "{get: () => 'en-US'});"
            },
        )
        browser.navigate(base_url)
        browser.wait_for("!document.getElementById('step-1').classList.contains('hidden')")
        first = browser.evaluate(
            "({heading: document.querySelector('#step-1 h2').textContent, "
            "selected: document.getElementById('lang-en').getAttribute('aria-pressed')})"
        )
        assert "Start with your situation" in first["heading"]
        assert first["selected"] == "true"

        browser.evaluate("document.getElementById('btn-step1-next').click()")
        browser.wait_for("!document.getElementById('step-2').classList.contains('hidden')")
        browser.evaluate(
            "document.querySelector('input[name=people-state][value=known]').click();"
            "document.getElementById('people-count').value='2';"
            "document.getElementById('health').value='healthy';"
            "document.getElementById('urgency').value='stable';"
            "document.getElementById('shelter').value='permanent_building';"
            "document.querySelector('input[name=threat-state][value=none]').click();"
            "document.querySelector('[data-action=situation-next]').click()"
        )
        browser.wait_for("!document.getElementById('step-3').classList.contains('hidden')")
        browser.evaluate(
            """['power','food','storage'].forEach(type=>{
              document.querySelector(`input[name=${type}-amount-state][value=unknown]`).click();
              document.querySelector(`input[name=${type}-rate-state][value=unknown]`).click();
            });
            document.querySelector('input[name=water-amount-state][value=known]').click();
            document.getElementById('water-amount').value='10';
            document.querySelector('input[name=water-rate-state][value=estimate]').click();
            document.getElementById('water-consumption').value='4';
            document.getElementById('water-intake').value='1';
            document.querySelector('input[name=fire-amount-state][value=known]').click();
            document.getElementById('fire-amount').value='5';
            document.querySelector('input[name=fire-rate-state][value=unknown]').click();
            document.getElementById('btn-review').click();"""
        )
        browser.wait_for("!document.getElementById('step-4').classList.contains('hidden')")
        state = browser.evaluate(
            """({
              resources: document.getElementById('summary-resources').textContent,
              plan: document.getElementById('plan-selection').textContent,
              primaryCount: document.querySelectorAll('input[name=primary-action]').length,
              completeDisabled: document.getElementById('btn-complete').disabled,
              initializedText: document.getElementById('hardware-summary').textContent,
            })"""
        )
        assert "10 L" in state["resources"]
        assert "4 L/day" in state["resources"]
        assert "total basis" in state["resources"]
        assert "Mixed sources" in state["resources"]
        assert "Complete" in state["plan"]
        assert state["primaryCount"] >= 1
        assert state["completeDisabled"] is True
        enabled = browser.evaluate(
            "document.querySelector('input[name=primary-action]').click();"
            "document.getElementById('assessment-confirmed').click();"
            "document.getElementById('btn-complete').disabled"
        )
        assert enabled is False
        initialized = browser.evaluate(
            "fetch('/api/init/status').then(r=>r.json()).then(x=>x.initialized)",
            await_promise=True,
        )
        assert initialized is False

        browser.evaluate("document.getElementById('lang-zh').click()")
        switched = browser.evaluate(
            """({
              resources: document.getElementById('summary-resources').textContent,
              progressHidden: document.querySelector('.progress').getAttribute('aria-hidden'),
              title: document.title,
              hardware: document.getElementById('hardware-summary').textContent,
              selectedPlan: document.querySelector('input[name=primary-action]:checked')?.value || '',
            })"""
        )
        assert "次" in switched["resources"]
        assert "总量口径" in switched["resources"]
        assert switched["progressHidden"] == "true"
        assert switched["title"] == "ALLSPARK — 首次状况评估"
        assert "正在检测" not in switched["hardware"]
        assert switched["selectedPlan"].startswith("survival-plan-")

        browser.evaluate(
            "showErrors([{field:'primary_action_id',code:'selection_required'}]);"
            "document.querySelector('#init-error-list a').click()"
        )
        browser.wait_for("document.activeElement.name==='primary-action'")
        assert browser.evaluate(
            "document.querySelector('#init-error-list a').getAttribute('href')"
        ) == "#plan-selection"


def test_zh_browser_locale_starts_on_language_step(tmp_path: Path) -> None:
    app = create_app(str(tmp_path / "init-zh.db"))
    with _serve_init(app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / "chrome-profile-zh"
    ) as browser:
        browser.call(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": "Object.defineProperty(navigator, 'language', "
                "{get: () => 'zh-CN'});"
            },
        )
        browser.navigate(base_url)
        browser.wait_for("!document.getElementById('step-1').classList.contains('hidden')")
        state = browser.evaluate(
            "({heading: document.querySelector('#step-1 h2').textContent, "
            "selected: document.getElementById('lang-zh').getAttribute('aria-pressed')})"
        )
        assert "先从你的处境开始" in state["heading"]
        assert state["selected"] == "true"


def test_known_empty_people_is_blocked_and_error_link_focuses_input(tmp_path: Path) -> None:
    app = create_app(str(tmp_path / "init-people-error.db"))
    with _serve_init(app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / "chrome-profile-people-error"
    ) as browser:
        browser.navigate(base_url)
        browser.wait_for("!document.getElementById('step-1').classList.contains('hidden')")
        browser.evaluate("document.getElementById('btn-step1-next').click()")
        browser.wait_for("!document.getElementById('step-2').classList.contains('hidden')")
        initial = browser.evaluate("document.getElementById('people-count').value")
        assert initial == ""

        browser.evaluate(
            "document.querySelector('input[name=people-state][value=known]').click();"
            "document.getElementById('health').value='healthy';"
            "document.getElementById('urgency').value='stable';"
            "document.getElementById('shelter').value='permanent_building';"
            "document.querySelector('input[name=threat-state][value=none]').click();"
            "document.querySelector('[data-action=situation-next]').click()"
        )
        browser.wait_for("!document.getElementById('init-errors').classList.contains('hidden')")
        state = browser.evaluate(
            "({active:document.activeElement.id,"
            "resourcesHidden:document.getElementById('step-3').classList.contains('hidden'),"
            "href:document.querySelector('#init-error-list a').getAttribute('href')})"
        )
        assert state == {
            "active": "init-errors",
            "resourcesHidden": True,
            "href": "#field-people_count",
        }

        browser.evaluate("document.querySelector('#init-error-list a').click()")
        browser.wait_for("document.activeElement.id==='people-count'")

        browser.evaluate(
            "showStep(3);"
            "showErrors([{field:'resources.water.rates.basis',code:'invalid_rate_basis'}]);"
            "document.querySelector('#init-error-list a').click()"
        )
        browser.wait_for(
            "document.activeElement.name==='water-rate-state'"
        )

        browser.evaluate(
            "showErrors([{field:'resources.water.rates',code:'outlier_confirmation'}]);"
            "document.querySelector('#init-error-list a').click()"
        )
        browser.wait_for("document.activeElement.id==='water-confirm-outlier'")
        visible = browser.evaluate(
            "!document.getElementById('water-outlier').classList.contains('hidden')"
        )
        assert visible is True
