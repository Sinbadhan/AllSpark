"""SHA-275: footer must fail closed when core status APIs are unavailable."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_sha196_browser import _Chrome, _chrome_binary, _serve
from tests.test_sha213_csp_browser import _assert_clean, _install_probe
from tests.test_web_ui_v11 import _client


@pytest.mark.parametrize(
    ("language", "unavailable", "phase_pending", "mode_pending"),
    [
        ("zh", "不可用", "阶段待评估", "待评估"),
        ("en", "unavailable", "Phase pending assessment", "Pending assessment"),
    ],
)
def test_footer_fails_closed_and_recovers_in_real_chrome(
    tmp_path: Path,
    language: str,
    unavailable: str,
    phase_pending: str,
    mode_pending: str,
) -> None:
    client = _client(str(tmp_path / f"footer-{language}.db"))
    client.post("/api/system/language", json={"language": language})

    with _serve(client.app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / f"chrome-profile-{language}"
    ) as browser:
        _install_probe(browser)
        browser.navigate(base_url)
        browser.evaluate("updateFooter()", await_promise=True)
        original = browser.evaluate(
            "document.getElementById('footer-status').textContent.trim()"
        )
        assert unavailable not in original

        scenarios = {
            "status_http": """path === '/api/status'
              ? Promise.resolve({_http_error: true, _http_status: 500})
              : originalApi(path, options)""",
            "health_http": """path === '/api/system/health'
              ? Promise.resolve({_http_error: true, _http_status: 503})
              : originalApi(path, options)""",
            "network": """path === '/api/status'
              ? Promise.reject(new Error('offline'))
              : originalApi(path, options)""",
        }
        for name, replacement in scenarios.items():
            state = browser.evaluate(
                f"""(async () => {{
                  const originalApi = window.api;
                  window.api = (path, options) => {replacement};
                  document.getElementById('footer-status').textContent = 'STALE NOMINAL';
                  document.getElementById('footer-resources').textContent = 'STALE FACTS';
                  await updateFooter();
                  const result = {{
                    status: document.getElementById('footer-status').textContent.trim(),
                    resources: document.getElementById('footer-resources').textContent.trim(),
                  }};
                  window.api = originalApi;
                  return result;
                }})()""",
                await_promise=True,
            )
            assert unavailable in state["status"], (name, state)
            assert "STALE" not in state["status"], (name, state)
            assert "STALE" not in state["resources"], (name, state)
            assert "--" in state["resources"], (name, state)
            assert phase_pending in state["resources"], (name, state)
            assert mode_pending in state["resources"], (name, state)

        recovered = browser.evaluate(
            """(async () => {
              await updateFooter();
              return {
                status: document.getElementById('footer-status').textContent.trim(),
                resources: document.getElementById('footer-resources').textContent.trim(),
              };
            })()""",
            await_promise=True,
        )
        assert unavailable not in recovered["status"]
        assert "STALE" not in recovered["resources"]
        _assert_clean(browser, f"Footer fail-closed ({language})")


def test_footer_source_has_no_silent_failure_fallback() -> None:
    source = Path("allspark/templates/base.html").read_text(encoding="utf-8")
    update = source.split("async function updateFooter()", 1)[1].split(
        "updateFooter();", 1
    )[0]
    assert "data?._http_error || health?._http_error" in update
    assert "api(\"/api/system/health\").catch" not in update
    assert "catch(e) {}" not in update
    assert "setUnavailable();" in update
