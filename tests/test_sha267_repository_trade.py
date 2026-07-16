"""SHA-267: Repository trade list API/UI contract regression."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_sha196_browser import _Chrome, _chrome_binary, _serve
from tests.test_sha213_csp_browser import _assert_clean, _install_probe
from tests.test_web_ui_v11 import _client

EXPECTED_FIELDS = {
    "id",
    "target",
    "offer_ids",
    "request_ids",
    "status",
    "created_at",
}


def _propose(client, *, target: str = "remote-alpha") -> str:
    response = client.post(
        "/api/trade/propose",
        json={
            "target_spark_id": target,
            "offer_ids": ["water/boiling", "shelter/repair"],
            "request_ids": ["medical/triage"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["trade_id"]


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


def _open_community_with_keyboard(browser: _Chrome) -> None:
    browser.evaluate(
        "document.querySelector('.file-tree-item[data-section=\"community\"]').focus()"
    )
    assert browser.evaluate("document.activeElement.tagName") == "BUTTON"
    assert browser.evaluate("document.activeElement.dataset.section") == "community"
    _press_enter(browser)
    browser.wait_for("currentSection === 'community'")


def _set_desktop_viewport(browser: _Chrome) -> None:
    browser.call(
        "Emulation.setDeviceMetricsOverride",
        {"width": 1280, "height": 844, "deviceScaleFactor": 1, "mobile": False},
    )


def test_non_empty_trade_api_has_one_exact_contract(tmp_path: Path) -> None:
    client = _client(str(tmp_path / "api.db"))
    trade_id = _propose(client)

    response = client.get("/api/trade/list")
    assert response.status_code == 200, response.text
    assert set(response.json()) == {"trades"}
    trades = response.json()["trades"]
    assert len(trades) == 1
    trade = trades[0]
    assert set(trade) == EXPECTED_FIELDS
    assert trade == {
        "id": trade_id,
        "target": "remote-alpha",
        "offer_ids": ["water/boiling", "shelter/repair"],
        "request_ids": ["medical/triage"],
        "status": "proposed",
        "created_at": trade["created_at"],
    }
    assert trade["created_at"]
    assert isinstance(trade["offer_ids"], list)
    assert isinstance(trade["request_ids"], list)
    assert all(isinstance(value, str) for value in trade["offer_ids"])
    assert all(isinstance(value, str) for value in trade["request_ids"])


def test_repository_template_consumes_only_the_list_api_contract() -> None:
    source = Path("allspark/templates/repository.html").read_text(encoding="utf-8")
    assert "const list = trades.trades;" in source
    assert "trades.trades ||" not in source
    assert "from_node" not in source
    assert "to_node" not in source
    assert "trade.offer_ids.length" in source
    assert "trade.request_ids.length" in source
    assert 'aria-live="polite"' in source
    assert 'class="trade-item" tabindex=' not in source


@pytest.mark.parametrize("language", ["zh", "en"])
def test_repository_renders_non_empty_trade_contract_in_real_chrome(
    tmp_path: Path, language: str
) -> None:
    client = _client(str(tmp_path / f"browser-{language}.db"))
    client.post("/api/system/language", json={"language": language})
    _propose(client, target="remote-北极星")

    with _serve(client.app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / f"chrome-profile-{language}"
    ) as browser:
        _install_probe(browser)
        _set_desktop_viewport(browser)
        browser.navigate(f"{base_url}/repository")
        browser.evaluate("initialRepositoryLoad", await_promise=True)
        _open_community_with_keyboard(browser)
        browser.wait_for("document.querySelectorAll('.trade-item').length === 1")

        state = browser.evaluate(
            """(() => {
              const region = document.getElementById('trade-list');
              return {
                text: region.textContent.replace(/\\s+/g, ' ').trim(),
                role: region.getAttribute('role'),
                live: region.getAttribute('aria-live'),
                atomic: region.getAttribute('aria-atomic'),
                label: region.getAttribute('aria-label'),
                displayTabStops: region.querySelectorAll('[tabindex]').length,
                itemCount: region.querySelectorAll('.trade-item').length,
              };
            })()"""
        )
        expected = (
            ["目标节点: remote-北极星", "状态: 已提议", "提供条目: 2", "请求条目: 1"]
            if language == "zh"
            else [
                "Target node: remote-北极星",
                "Status: Proposed",
                "Offered entries: 2",
                "Requested entries: 1",
            ]
        )
        assert all(marker in state["text"] for marker in expected), state
        assert "undefined" not in state["text"]
        assert "from_node" not in state["text"]
        assert "to_node" not in state["text"]
        assert state["role"] == "status"
        assert state["live"] == "polite"
        assert state["atomic"] == "true"
        assert state["label"]
        assert state["displayTabStops"] == 0
        assert state["itemCount"] == 1

        same_region = browser.evaluate(
            """(async () => {
              const before = document.getElementById('trade-list');
              await loadCommunityData();
              return before === document.getElementById('trade-list');
            })()""",
            await_promise=True,
        )
        assert same_region is True

        browser.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 320, "height": 844, "deviceScaleFactor": 1, "mobile": True},
        )
        layout = browser.evaluate(
            """(() => {
              const region = document.getElementById('trade-list');
              const item = region.querySelector('.trade-item');
              return {
                pageFits: document.documentElement.scrollWidth <= innerWidth + 1,
                regionFits: region.scrollWidth <= region.clientWidth + 1,
                itemFits: item.scrollWidth <= item.clientWidth + 1,
              };
            })()"""
        )
        assert layout == {"pageFits": True, "regionFits": True, "itemFits": True}
        _assert_clean(browser, f"Repository trade list ({language})")


def test_repository_shows_explicit_failure_for_invalid_trade_contract_in_chrome(
    tmp_path: Path,
) -> None:
    client = _client(str(tmp_path / "invalid.db"))
    client.post("/api/system/language", json={"language": "en"})
    trade_id = _propose(client)
    service = client.app.state.container.get("trade_engine")
    offer = service.get_trade(trade_id)
    assert offer is not None
    offer.offer_knowledge_ids = "not-an-array"

    response = client.get("/api/trade/list")
    assert response.status_code == 500
    assert response.json()["status"] == "error"
    assert response.json()["error"] == "Unable to read the trade list"

    with _serve(client.app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / "chrome-profile-invalid"
    ) as browser:
        _install_probe(browser)
        _set_desktop_viewport(browser)
        browser.navigate(f"{base_url}/repository")
        browser.evaluate("initialRepositoryLoad", await_promise=True)
        _open_community_with_keyboard(browser)
        browser.wait_for(
            "document.getElementById('trade-list').textContent.includes('Unable to load trades')"
        )
        text = browser.evaluate("document.getElementById('trade-list').textContent.trim()")
        assert text == "Unable to load trades. Check system status and retry."
        assert "No trades yet" not in text
        assert browser.evaluate("document.querySelectorAll('.trade-item').length") == 0
        _assert_clean(browser, "Repository invalid trade list")
