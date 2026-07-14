"""SHA-218: Config must execute against real API schemas in Chrome."""

from __future__ import annotations

from pathlib import Path

from tests.test_sha196_browser import _Chrome, _chrome_binary, _serve
from tests.test_web_ui_v11 import _client


def test_config_runtime_and_degraded_states_in_real_chrome(tmp_path: Path) -> None:
    client = _client(str(tmp_path / "config.db"))
    client.post("/api/system/language", json={"language": "en"})

    with _serve(client.app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / "chrome-profile"
    ) as browser:
        browser.call(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                  window.__configErrors = [];
                  addEventListener('error', event =>
                    window.__configErrors.push(String(event.error || event.message)));
                  addEventListener('unhandledrejection', event =>
                    window.__configErrors.push(String(event.reason)));
                """
            },
        )
        browser.navigate(f"{base_url}/config")
        browser.evaluate("initialConfigLoad", await_promise=True)
        normal = browser.evaluate(
            """({
              errors: window.__configErrors,
              version: document.getElementById('cfg-version').textContent,
              language: document.getElementById('cfg-language').textContent,
              license: document.getElementById('cfg-license').textContent,
              homepage: document.querySelector('#cfg-homepage a')?.href,
              health: document.getElementById('cfg-health').textContent,
              llm: document.getElementById('cfg-llm').textContent,
              tier: document.getElementById('cfg-tier').textContent,
              flags: document.getElementById('cfg-flags').textContent,
            })"""
        )

        browser.evaluate(
            """(() => {
              window.api = async () => { throw new Error('forced outage'); };
              return loadConfig();
            })()""",
            await_promise=True,
        )
        degraded = browser.evaluate(
            """({
              errors: window.__configErrors,
              version: document.getElementById('cfg-version').textContent,
              health: document.getElementById('cfg-health').textContent,
              llm: document.getElementById('cfg-llm').textContent,
              tier: document.getElementById('cfg-tier').textContent,
              flags: document.getElementById('cfg-flags').textContent,
            })"""
        )

    assert normal["errors"] == []
    assert normal["version"] not in {"", "--"}
    assert normal["language"] == "en"
    assert normal["license"] == "Apache-2.0"
    assert normal["homepage"].startswith("https://")
    assert "%" in normal["health"] and "degraded" in normal["health"]
    assert "not loaded" in normal["llm"]
    assert normal["tier"] not in {"", "--"}
    assert normal["flags"].strip() not in {"", "--"}

    assert degraded["errors"] == []
    for field in ("version", "health", "llm", "tier", "flags"):
        assert degraded[field] == "unavailable"
