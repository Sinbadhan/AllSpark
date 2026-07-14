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


def test_language_first_and_questionnaire_switches_live(tmp_path: Path) -> None:
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
        assert "Language" in first["heading"]
        assert first["selected"] == "true"

        browser.evaluate("goStep(2)")
        browser.wait_for("!document.getElementById('hw-info').classList.contains('hidden')")
        browser.evaluate("goStep(1); document.getElementById('lang-zh').click(); goStep(2)")
        assert "硬件检测" in browser.evaluate("document.querySelector('#step-2 h2').textContent")
        browser.evaluate("goStep(1); document.getElementById('lang-en').click(); goStep(2)")
        browser.wait_for("!document.getElementById('btn-step2-next').disabled")
        browser.evaluate("goStep(3); goStep(4)")
        browser.wait_for("document.querySelectorAll('#questionnaire select').length >= 4")
        state = browser.evaluate(
            """({
              options: Array.from(document.querySelectorAll('#questionnaire option')).map(o => o.textContent),
              labels: Array.from(document.querySelectorAll('#questionnaire select')).map(s => s.labels[0]?.textContent),
              skipTag: document.querySelector('.step-skip').tagName,
            })"""
        )
        assert any("Urban" in option for option in state["options"])
        assert all(state["labels"])
        assert state["skipTag"] == "BUTTON"

        browser.evaluate(
            "document.getElementById('q-location').value = 'urban'; "
            "goStep(1); document.getElementById('lang-zh').click(); goStep(4)"
        )
        switched = browser.evaluate(
            """({
              value: document.getElementById('q-location').value,
              options: Array.from(document.querySelectorAll('#q-location option')).map(o => o.textContent),
              label: document.getElementById('q-location').labels[0].textContent,
            })"""
        )
        assert switched["value"] == "urban"
        assert any("城市" in option for option in switched["options"])
        assert "位置" in switched["label"]

        browser.evaluate(
            "goStep(1); document.getElementById('lang-en').click(); goStep(4)"
        )
        assert browser.evaluate("document.getElementById('q-location').value") == "urban"


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
        assert "语言" in state["heading"]
        assert state["selected"] == "true"
