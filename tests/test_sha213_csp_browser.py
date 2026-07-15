"""SHA-213: enforcing CSP remains violation-free across all Web surfaces."""

from __future__ import annotations

from pathlib import Path

from allspark.adapters.web_ui import create_app
from tests.test_sha196_browser import _Chrome, _chrome_binary, _serve
from tests.test_web_ui_v11 import _client

_CSP_PROBE = """
  window.__cspViolations = [];
  window.__runtimeErrors = [];
  document.addEventListener('securitypolicyviolation', event => {
    window.__cspViolations.push({
      directive: event.effectiveDirective,
      blocked: event.blockedURI,
      sample: event.sample,
    });
  });
  addEventListener('error', event => {
    window.__runtimeErrors.push(String(event.error || event.message));
  });
  addEventListener('unhandledrejection', event => {
    window.__runtimeErrors.push(String(event.reason));
  });
"""


def _install_probe(browser: _Chrome) -> None:
    browser.call("Page.addScriptToEvaluateOnNewDocument", {"source": _CSP_PROBE})


def _assert_clean(browser: _Chrome, page: str) -> None:
    browser.evaluate(
        "new Promise(resolve => setTimeout(() => resolve(true), 100))",
        await_promise=True,
    )
    state = browser.evaluate(
        "({violations: window.__cspViolations, errors: window.__runtimeErrors})"
    )
    assert state["violations"] == [], f"{page} CSP violations: {state['violations']}"
    assert state["errors"] == [], f"{page} runtime errors: {state['errors']}"


def test_enforcing_csp_on_initialized_pages(tmp_path: Path) -> None:
    client = _client(str(tmp_path / "initialized.db"))
    with _serve(client.app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / "chrome-initialized"
    ) as browser:
        _install_probe(browser)

        browser.navigate(base_url)
        browser.wait_for("document.querySelectorAll('.resource-card').length > 0")
        browser.evaluate("document.querySelector('[data-subtab=chat]').click()")
        browser.wait_for(
            "!document.getElementById('subtab-chat').classList.contains('hidden')"
        )
        browser.evaluate("document.querySelector('[data-index-action=toggle-briefing]').click()")
        browser.wait_for("document.getElementById('briefing-full').style.display === 'block'")
        browser.evaluate("document.querySelector('.resource-card').click()")
        browser.wait_for("document.getElementById('res-edit-modal')?.style.display === 'flex'")
        browser.evaluate(
            "document.querySelector('[data-index-action=close-resource-edit]').click()"
        )
        _assert_clean(browser, "Dashboard")

        browser.navigate(f"{base_url}/system")
        browser.wait_for("document.querySelector('#module-table tr') !== null")
        browser.evaluate("document.querySelector('[data-system-action=refresh-system]').click()")
        browser.evaluate("document.querySelector('[data-system-action=apply-modes]').click()")
        browser.wait_for("document.querySelector('#toast-stack .toast') !== null")
        _assert_clean(browser, "System")

        browser.navigate(f"{base_url}/config")
        browser.evaluate("initialConfigLoad", await_promise=True)
        browser.wait_for("document.getElementById('cfg-version').textContent !== '--'")
        _assert_clean(browser, "Config")

        browser.navigate(f"{base_url}/executions")
        browser.wait_for("document.getElementById('stat-total').textContent !== ''")
        browser.evaluate("document.querySelector('[data-exectab=goals]').click()")
        browser.wait_for("document.getElementById('exectab-goals').style.display !== 'none'")
        browser.evaluate("document.querySelector('[data-exec-action=refresh-goals]').click()")
        _assert_clean(browser, "Executions")

        browser.navigate(f"{base_url}/repository")
        browser.evaluate("initialRepositoryLoad", await_promise=True)
        browser.wait_for("document.getElementById('repo-search') !== null")
        browser.evaluate("document.getElementById('file-tree-toggle').click()")
        assert browser.evaluate(
            "document.getElementById('file-tree-toggle').getAttribute('aria-expanded')"
        ) == "true"
        browser.evaluate("document.getElementById('btn-skf-export').click()")
        browser.wait_for("currentSection === 'skf'")
        browser.evaluate("document.querySelector('[data-repo-action=skf-info]').click()")
        _assert_clean(browser, "Repository")


def test_enforcing_csp_on_init_and_login(tmp_path: Path) -> None:
    init_app = create_app(str(tmp_path / "init.db"))
    with _serve(init_app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / "chrome-init"
    ) as browser:
        _install_probe(browser)
        browser.navigate(base_url)
        browser.wait_for("!document.getElementById('step-1').classList.contains('hidden')")
        browser.evaluate("document.getElementById('lang-en').click()")
        browser.evaluate("document.getElementById('btn-step1-next').click()")
        browser.wait_for("!document.getElementById('step-2').classList.contains('hidden')")
        _assert_clean(browser, "Init")

    login_path = tmp_path / "login.db"
    _client(str(login_path))
    protected_app = create_app(str(login_path), token="audit-secret")
    with _serve(protected_app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / "chrome-login"
    ) as browser:
        _install_probe(browser)
        browser.navigate(f"{base_url}/login")
        browser.evaluate(
            "document.getElementById('token').value = 'wrong'; "
            "document.getElementById('login-btn').click()"
        )
        browser.wait_for("document.getElementById('err').textContent.trim() !== ''")
        _assert_clean(browser, "Login")
