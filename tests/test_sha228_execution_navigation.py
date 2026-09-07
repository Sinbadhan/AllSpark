"""SHA-228: Executions is navigation, not a misleading global command."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from allspark.core.i18n import get_language, set_language
from tests.test_sha196_browser import _Chrome, _chrome_binary, _serve
from tests.test_web_ui_v11 import _client


class _DelayedExecutionHTML:
    """Expose URL commitment before the real action-page body is parsed."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.release_body = threading.Event()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def delayed_send(message: Message) -> None:
            if (
                scope.get("path") == "/executions"
                and message["type"] == "http.response.body"
                and message.get("body")
            ):
                body = message["body"]
                split = body.index(b"<body")
                await send({**message, "body": body[:split], "more_body": True})
                assert await asyncio.to_thread(self.release_body.wait, 10), (
                    "Test did not release the delayed execution document"
                )
                await send({**message, "body": body[split:]})
                return
            await send(message)

        await self.app(scope, receive, delayed_send)


def _wait_for_execution_document(browser: _Chrome) -> None:
    # Location changes when navigation commits, before HTML parsing finishes.
    # Readiness is not a replacement for the exact navigation assertions below.
    browser.wait_for(
        "location.pathname === '/executions' && document.readyState === 'complete'"
    )


@pytest.fixture(autouse=True)
def _restore_process_language():
    original = get_language()
    yield
    set_language(original)


@pytest.mark.parametrize(
    ("language", "expected_label"),
    [("zh", "行动"), ("en", "Actions")],
)
def test_execution_navigation_is_consistent_across_pages_and_viewports(
    tmp_path: Path, language: str, expected_label: str
) -> None:
    client = _client(str(tmp_path / f"execution-navigation-{language}.db"))
    response = client.post("/api/system/language", json={"language": language})
    assert response.status_code == 200

    delayed_app = _DelayedExecutionHTML(client.app)
    with _serve(delayed_app) as base_url, _Chrome(
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
        # Deterministically reproduce the former URL-only wait returning while
        # both real navigation links are still absent from the incoming DOM.
        assert browser.evaluate("document.readyState") == "loading"
        assert browser.evaluate("document.querySelectorAll('a[href=\"/executions\"]').length") == 0
        delayed_app.release_body.set()
        _wait_for_execution_document(browser)
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
        delayed_app.release_body.clear()
        browser.evaluate(
            "document.querySelector('#mobile-nav a[href=\"/executions\"]').click()"
        )
        browser.wait_for("location.pathname === '/executions'")
        assert browser.evaluate("document.readyState") == "loading"
        delayed_app.release_body.set()
        _wait_for_execution_document(browser)
        assert browser.evaluate(
            "document.querySelector('#mobile-nav a[href=\"/executions\"]')"
            ".getAttribute('aria-current')"
        ) == "page"
