"""Browser harness tests that never launch a browser process."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.test_sha196_browser import _Chrome


class _Messages:
    def __init__(self, messages: list[dict] | None = None):
        self.messages = list(messages or [])
        self.sent: list[dict] = []

    def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))

    def recv(self, *, timeout: float) -> str:
        if not self.messages:
            raise TimeoutError
        return json.dumps(self.messages.pop(0))


def test_cdp_call_keeps_events_while_waiting_for_its_response(tmp_path: Path) -> None:
    browser = _Chrome("unused", tmp_path)
    browser.ws = _Messages(
        [
            {"method": "Network.loadingFailed", "params": {"errorText": "offline"}},
            {"id": 1, "result": {"value": "ok"}},
        ]
    )

    assert browser.call("Runtime.test", timeout=0.5)["result"]["value"] == "ok"
    assert browser.ws.sent == [{"id": 1, "method": "Runtime.test", "params": {}}]
    assert browser._recent_events[-1]["method"] == "Network.loadingFailed"


def test_cdp_timeout_includes_method_and_recent_events(tmp_path: Path) -> None:
    browser = _Chrome("unused", tmp_path)
    browser.ws = _Messages()
    browser._recent_events = [{"method": "Page.lifecycleEvent", "params": {}}]

    with pytest.raises(AssertionError, match="Runtime.never.*Page.lifecycleEvent"):
        browser.call("Runtime.never", timeout=0.01)


def test_harness_isolated_profile_flags_and_failure_artifacts_are_required() -> None:
    source = Path("tests/test_sha196_browser.py").read_text(encoding="utf-8")
    for flag in (
        '"--password-store=basic"',
        '"--use-mock-keychain"',
        '"--disable-extensions"',
        'f"--user-data-dir={self.profile}"',
    ):
        assert flag in source
    assert "Page.captureScreenshot" in source
    assert "failure-cdp-events.json" in source
