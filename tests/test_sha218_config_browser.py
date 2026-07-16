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
              release: document.getElementById('cfg-release').textContent,
              scope: document.getElementById('cfg-scope').textContent,
              language: document.getElementById('cfg-language').textContent,
              license: document.getElementById('cfg-license').textContent,
              homepage: document.querySelector('#cfg-homepage a')?.href,
              health: document.getElementById('cfg-health').textContent,
              llm: document.getElementById('cfg-llm').textContent,
              mode: document.getElementById('cfg-mode').textContent,
              capabilities: document.getElementById('cfg-capabilities').textContent,
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
              release: document.getElementById('cfg-release').textContent,
              scope: document.getElementById('cfg-scope').textContent,
              health: document.getElementById('cfg-health').textContent,
              llm: document.getElementById('cfg-llm').textContent,
              mode: document.getElementById('cfg-mode').textContent,
              capabilities: document.getElementById('cfg-capabilities').textContent,
            })"""
        )

    assert normal["errors"] == []
    assert normal["version"] not in {"", "--"}
    assert "Release Candidate" in normal["release"]
    assert "Not Stable" in normal["release"]
    assert "Assess → Decide → Act → Reassess" in normal["scope"]
    assert normal["language"] == "en"
    assert normal["license"] == "Apache-2.0"
    assert normal["homepage"].startswith("https://")
    assert normal["health"] == "100% · Healthy"
    assert "Experimental" in normal["llm"] and "not loaded" in normal["llm"]
    assert normal["mode"] == "PROCESS"
    for status in ("Supported", "Testing", "Experimental", "Future"):
        assert status in normal["capabilities"]

    assert degraded["errors"] == []
    for field in ("version", "release", "scope", "health", "llm", "mode", "capabilities"):
        assert degraded[field] == "unavailable"
