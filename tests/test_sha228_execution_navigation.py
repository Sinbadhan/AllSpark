"""SHA-228: Executions is navigation, not a misleading global command."""

from __future__ import annotations

from pathlib import Path

import pytest

from allspark.core.i18n import get_language, set_language
from tests.test_sha196_browser import _Chrome, _chrome_binary, _serve
from tests.test_web_ui_v11 import _client


@pytest.fixture(autouse=True)
def _restore_process_language():
    original = get_language()
    yield
    set_language(original)


@pytest.mark.parametrize(
    ("language", "expected_label"),
    [("zh", "执行中心"), ("en", "Executions")],
)
def test_execution_navigation_is_consistent_across_pages_and_viewports(
    tmp_path: Path, language: str, expected_label: str
) -> None:
    client = _client(str(tmp_path / f"execution-navigation-{language}.db"))
    response = client.post("/api/system/language", json={"language": language})
    assert response.status_code == 200

    with _serve(client.app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / f"chrome-profile-{language}"
    ) as browser:
        browser.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1280, "height": 800, "deviceScaleFactor": 1, "mobile": False},
        )
        browser.navigate(base_url)
        dashboard = browser.evaluate(
            """(() => {
              const desktop = document.querySelector('.sidebar a[href="/executions"]');
              const mobile = document.querySelector('#mobile-nav a[href="/executions"]');
              const label = link => Array.from(link.childNodes)
                .filter(node => node.nodeType === Node.TEXT_NODE)
                .map(node => node.textContent.trim()).filter(Boolean).join(' ');
              return {
                commandCount: document.querySelectorAll('.exec-btn').length,
                desktopTag: desktop?.tagName,
                mobileTag: mobile?.tagName,
                desktopLabel: label(desktop),
                mobileLabel: label(mobile),
                desktopCurrent: desktop?.getAttribute('aria-current'),
                mobileCurrent: mobile?.getAttribute('aria-current'),
              };
            })()"""
        )
        assert dashboard == {
            "commandCount": 0,
            "desktopTag": "A",
            "mobileTag": "A",
            "desktopLabel": expected_label,
            "mobileLabel": expected_label,
            "desktopCurrent": None,
            "mobileCurrent": None,
        }

        browser.evaluate(
            "document.querySelector('.sidebar a[href=\"/executions\"]').click()"
        )
        browser.wait_for("location.pathname === '/executions'")
        current = browser.evaluate(
            """(() => {
              const links = Array.from(document.querySelectorAll('a[href="/executions"]'));
              const label = link => Array.from(link.childNodes)
                .filter(node => node.nodeType === Node.TEXT_NODE)
                .map(node => node.textContent.trim()).filter(Boolean).join(' ');
              return {
                path: location.pathname,
                commandCount: document.querySelectorAll('.exec-btn').length,
                labels: links.map(label),
                current: links.map(link => link.getAttribute('aria-current')),
                active: links.map(link => link.classList.contains('active')),
              };
            })()"""
        )
        assert current == {
            "path": "/executions",
            "commandCount": 0,
            "labels": [expected_label, expected_label],
            "current": ["page", "page"],
            "active": [True, True],
        }

        browser.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True},
        )
        browser.navigate(base_url)
        browser.evaluate("document.getElementById('mobile-nav-toggle').click()")
        browser.wait_for(
            "document.getElementById('mobile-nav').classList.contains('open')"
        )
        browser.evaluate(
            "document.querySelector('#mobile-nav a[href=\"/executions\"]').click()"
        )
        browser.wait_for("location.pathname === '/executions'")
        assert browser.evaluate(
            "document.querySelector('#mobile-nav a[href=\"/executions\"]')"
            ".getAttribute('aria-current')"
        ) == "page"
