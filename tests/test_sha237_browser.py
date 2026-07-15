"""SHA-237: real-Chrome resource editor contract and narrow viewport gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_sha196_browser import _Chrome, _chrome_binary, _serve
from tests.test_web_ui_v11 import _client

VIEWPORTS = (
    (320, 568),
    (360, 320),  # Mobile landscape / short visual viewport.
    (390, 844),
    (430, 932),
)


def _set_viewport(browser: _Chrome, width: int, height: int) -> None:
    browser.call(
        "Emulation.setDeviceMetricsOverride",
        {
            "width": width,
            "height": height,
            "deviceScaleFactor": 1,
            "mobile": True,
        },
    )


def _open_resource(browser: _Chrome, resource_type: str) -> None:
    browser.evaluate(
        f"document.querySelector('.resource-card[data-resource-type=\"{resource_type}\"]').click()"
    )
    browser.wait_for(
        "document.getElementById('res-edit-modal')?.style.display === 'flex'"
    )


def _editor_layout(browser: _Chrome) -> dict:
    return browser.evaluate(
        """(() => {
          const modal = document.getElementById('res-edit-modal');
          const card = modal.querySelector('[role="dialog"]');
          const actions = modal.querySelector('.resource-edit-actions');
          const cardRect = card.getBoundingClientRect();
          const actionsRect = actions.getBoundingClientRect();
          const buttons = Array.from(actions.querySelectorAll('button'));
          const visible = id => {
            const element = document.getElementById(id);
            return typeof element.checkVisibility === 'function'
              ? element.checkVisibility()
              : element.getClientRects().length > 0;
          };
          return {
            viewport: [innerWidth, innerHeight],
            pageFits: document.documentElement.scrollWidth <= innerWidth + 1,
            cardFitsHorizontally: cardRect.left >= -1 && cardRect.right <= innerWidth + 1,
            cardFitsVertically: cardRect.top >= -1 && cardRect.bottom <= innerHeight + 1,
            cardScrolls: card.scrollHeight >= card.clientHeight,
            cardHasNoHorizontalOverflow: card.scrollWidth <= card.clientWidth + 1,
            actionsPosition: getComputedStyle(actions).position,
            actionsVisible: actionsRect.top >= cardRect.top - 1 &&
              actionsRect.bottom <= cardRect.bottom + 21,
            buttonsVisible: buttons.every(button => {
              const rect = button.getBoundingClientRect();
              return rect.top >= cardRect.top - 1 && rect.bottom <= cardRect.bottom + 1 &&
                rect.left >= cardRect.left - 1 && rect.right <= cardRect.right + 1;
            }),
            advancedOpen: document.getElementById('res-edit-advanced').open,
            amountVisible: visible('res-edit-amount'),
            peopleVisible: visible('res-edit-people'),
            consumptionVisible: visible('res-edit-consumption'),
            capacityVisible: visible('res-edit-capacity-wrap'),
            capacityDisplay: getComputedStyle(
              document.getElementById('res-edit-capacity-wrap')
            ).display,
          };
        })()"""
    )


@pytest.mark.parametrize(
    ("language", "expected_title", "expected_unknown"),
    [
        ("zh", "更新资源", "人均：暂时未知"),
        ("en", "Update resource", "Per person: unknown for now"),
    ],
)
def test_resource_editor_progressively_discloses_fields_without_mobile_overflow(
    tmp_path: Path, language: str, expected_title: str, expected_unknown: str
) -> None:
    client = _client(str(tmp_path / f"resource-editor-{language}.db"))
    assert client.post("/api/system/language", json={"lang": language}).status_code == 200
    assert client.post(
        "/api/resources",
        json={
            "type": "water",
            "amount": 10,
            "daily_consumption": 2,
            "daily_intake": 1,
            "people_count": 2,
            "input_kind": "estimate",
        },
    ).status_code == 200
    assert client.post(
        "/api/resources",
        json={
            "type": "storage",
            "amount": 80,
            "daily_consumption": 2,
            "daily_intake": 1,
            "capacity": 100,
            "capacity_known": True,
            "people_count": 2,
        },
    ).status_code == 200

    with _serve(client.app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / f"chrome-profile-{language}"
    ) as browser:
        browser.navigate(base_url)
        browser.wait_for("document.querySelectorAll('.resource-card').length >= 5")

        # The resource type must be bound before the first conversion, and a
        # subsequent editor must not inherit the previous resource's unit.
        _set_viewport(browser, 1280, 800)
        _open_resource(browser, "storage")
        first_conversion = browser.evaluate(
            "document.getElementById('res-edit-conversion').textContent"
        )
        assert "40.00" in first_conversion
        assert "GB" in first_conversion
        browser.evaluate("closeResEdit()")
        _open_resource(browser, "water")
        second_conversion = browser.evaluate(
            "document.getElementById('res-edit-conversion').textContent"
        )
        assert "5.00" in second_conversion
        assert " L" in second_conversion
        assert "GB" not in second_conversion
        browser.evaluate("closeResEdit()")

        for width, height in VIEWPORTS:
            _set_viewport(browser, width, height)
            browser.evaluate("closeResEdit()")
            _open_resource(browser, "water")
            state = _editor_layout(browser)
            assert state["viewport"] == [width, height]
            for key in (
                "pageFits",
                "cardFitsHorizontally",
                "cardFitsVertically",
                "cardHasNoHorizontalOverflow",
                "actionsVisible",
                "buttonsVisible",
                "amountVisible",
                "peopleVisible",
            ):
                assert state[key] is True, f"{language} {width}x{height}: {key}: {state}"
            assert state["actionsPosition"] == "sticky"
            assert state["advancedOpen"] is False
            assert state["consumptionVisible"] is False
            assert state["capacityVisible"] is False
            assert state["capacityDisplay"] == "none"
            assert expected_title in browser.evaluate(
                "document.getElementById('res-edit-title').textContent"
            )

        # A fail-closed backend snapshot renders empty values, never numeric
        # sentinels or a fabricated per-person zero.
        browser.evaluate("closeResEdit()")
        _open_resource(browser, "fire")
        initial_unknown = browser.evaluate(
            """(() => ({
              values: ['amount', 'consumption', 'intake', 'capacity'].map(
                field => document.getElementById(`res-edit-${field}`).value
              ),
              amountDisabled: document.getElementById('res-edit-amount').disabled,
              amountUnknown: document.querySelector(
                '[data-resource-known-field="amount"]'
                + '[data-resource-known-value="false"]'
              ).getAttribute('aria-pressed'),
              conversion: document.getElementById('res-edit-conversion').textContent,
            }))()"""
        )
        assert initial_unknown == {
            "values": ["", "", "", ""],
            "amountDisabled": True,
            "amountUnknown": "true",
            "conversion": expected_unknown,
        }
        browser.evaluate("closeResEdit()")
        _open_resource(browser, "water")

        kind_state = browser.evaluate(
            """(() => {
              const selected = document.querySelector(
                '[data-resource-input-kind="estimate"]'
              );
              const observed = document.querySelector(
                '[data-resource-input-kind="observed"]'
              );
              return {
                estimate: selected.getAttribute('aria-pressed'),
                observed: observed.getAttribute('aria-pressed'),
                active: document.activeElement.dataset.resourceInputKind,
              };
            })()"""
        )
        assert kind_state == {"estimate": "true", "observed": "false", "active": "estimate"}

        chip_style = browser.evaluate(
            """(() => {
              const selected = document.querySelector(
                '[data-resource-input-kind="estimate"]'
              );
              const hoverTarget = document.querySelector(
                '[data-resource-known-field="amount"]'
                + '[data-resource-known-value="false"]'
              );
              const rect = hoverTarget.getBoundingClientRect();
              return {
                selectedBackground: getComputedStyle(selected).backgroundColor,
                selectedBorder: getComputedStyle(selected).borderColor,
                hoverBorderBefore: getComputedStyle(hoverTarget).borderColor,
                hoverPoint: [rect.left + rect.width / 2, rect.top + rect.height / 2],
              };
            })()"""
        )
        assert chip_style["selectedBackground"] != "rgba(0, 0, 0, 0)"
        assert chip_style["selectedBorder"] != chip_style["hoverBorderBefore"]
        browser.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseMoved",
                "x": chip_style["hoverPoint"][0],
                "y": chip_style["hoverPoint"][1],
            },
        )
        browser.wait_for(
            "getComputedStyle(document.querySelector("
            "'[data-resource-known-field=\"amount\"]"
            "[data-resource-known-value=\"false\"]'"
            ")).borderColor !== 'rgb(42, 42, 42)'"
        )
        hover_style = browser.evaluate(
            """(() => {
              const target = document.querySelector(
                '[data-resource-known-field="amount"]'
                + '[data-resource-known-value="false"]'
              );
              return {
                hovered: target.matches(':hover'),
                border: getComputedStyle(target).borderColor,
              };
            })()"""
        )
        assert hover_style["hovered"] is True
        assert hover_style["border"] != chip_style["hoverBorderBefore"]

        browser.call(
            "Input.dispatchKeyEvent",
            {"type": "keyDown", "key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9},
        )
        browser.call(
            "Input.dispatchKeyEvent",
            {"type": "keyUp", "key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9},
        )
        focus_style = browser.evaluate(
            """(() => ({
              focusVisible: document.activeElement.matches(':focus-visible'),
              outlineStyle: getComputedStyle(document.activeElement).outlineStyle,
              outlineWidth: getComputedStyle(document.activeElement).outlineWidth,
            }))()"""
        )
        assert focus_style["focusVisible"] is True
        assert focus_style["outlineStyle"] == "solid"
        assert float(focus_style["outlineWidth"].removesuffix("px")) >= 2

        # The two-state field control is mutually exclusive and disabling a field
        # makes its unknown semantics explicit to keyboard and assistive tech.
        unknown_state = browser.evaluate(
            """(() => {
              document.querySelector(
                '[data-resource-known-field="amount"][data-resource-known-value="false"]'
              ).click();
              const input = document.getElementById('res-edit-amount');
              return {
                known: document.querySelector(
                  '[data-resource-known-field="amount"][data-resource-known-value="true"]'
                ).getAttribute('aria-pressed'),
                unknown: document.querySelector(
                  '[data-resource-known-field="amount"][data-resource-known-value="false"]'
                ).getAttribute('aria-pressed'),
                disabled: input.disabled,
                ariaDisabled: input.getAttribute('aria-disabled'),
                value: input.value,
                conversion: document.getElementById(
                  'res-edit-conversion'
                ).textContent,
              };
            })()"""
        )
        assert unknown_state == {
            "known": "false",
            "unknown": "true",
            "disabled": True,
            "ariaDisabled": "true",
            "value": "",
            "conversion": expected_unknown,
        }
        browser.evaluate(
            "document.querySelector('[data-resource-known-field=\"amount\"]"
            "[data-resource-known-value=\"true\"]').click()"
        )
        restored_known = browser.evaluate(
            """(() => ({
              value: document.getElementById('res-edit-amount').value,
              disabled: document.getElementById('res-edit-amount').disabled,
              conversion: document.getElementById('res-edit-conversion').textContent,
            }))()"""
        )
        assert restored_known == {
            "value": "",
            "disabled": False,
            "conversion": expected_unknown,
        }
        browser.evaluate('saveResource("water")', await_promise=True)
        assert browser.evaluate(
            "document.getElementById('res-edit-modal').style.display"
        ) == "flex"
        assert browser.evaluate(
            "document.querySelector('.resource-card[data-resource-type=\"water\"]')"
            ".dataset.resourceAmount"
        ) == "10"

        # The focus trap includes all segmented buttons and the details summary.
        browser.evaluate(
            """(() => {
              const first = document.querySelector('[data-resource-input-kind="observed"]');
              first.focus();
              first.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'Tab', shiftKey: true, bubbles: true, cancelable: true
              }));
            })()"""
        )
        assert browser.evaluate("document.activeElement.id") == "res-edit-save"

        # Storage alone exposes capacity, and the sticky actions remain reachable
        # after the advanced section expands in the short landscape viewport.
        _set_viewport(browser, 360, 320)
        browser.evaluate("closeResEdit()")
        _open_resource(browser, "storage")
        browser.evaluate("document.getElementById('res-edit-advanced').open = true")
        expanded = browser.evaluate(
            """(() => {
              const card = document.querySelector('#res-edit-modal [role="dialog"]');
              const capacity = document.getElementById('res-edit-capacity');
              const actions = document.querySelector('.resource-edit-actions');
              capacity.focus();
              capacity.scrollIntoView({block: 'nearest'});
              const capacityRect = capacity.getBoundingClientRect();
              const actionsRect = actions.getBoundingClientRect();
              return {
                consumptionVisible: document.getElementById(
                  'res-edit-consumption'
                ).getClientRects().length > 0,
                capacityVisible: capacity.getClientRects().length > 0,
                capacityEnabled: !capacity.disabled,
                cardScrolled: card.scrollTop > 0,
                fieldNotCovered: capacityRect.bottom <= actionsRect.top + 1,
                saveVisible: document.getElementById(
                  'res-edit-save'
                ).getClientRects().length > 0,
                pageFits: document.documentElement.scrollWidth <= innerWidth + 1,
              };
            })()"""
        )
        assert expanded == {
            "consumptionVisible": True,
            "capacityVisible": True,
            "capacityEnabled": True,
            "cardScrolled": True,
            "fieldNotCovered": True,
            "saveVisible": True,
            "pageFits": True,
        }


def test_resource_outlier_confirmation_cancel_and_retry_in_real_chrome(
    tmp_path: Path,
) -> None:
    client = _client(str(tmp_path / "resource-confirm.db"))
    assert client.post(
        "/api/resources",
        json={
            "type": "water",
            "amount": 10,
            "daily_consumption": 2,
            "daily_intake": 1,
            "people_count": 2,
            "input_kind": "estimate",
        },
    ).status_code == 200

    with _serve(client.app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / "chrome-profile-confirm"
    ) as browser:
        _set_viewport(browser, 320, 568)
        browser.navigate(base_url)
        browser.wait_for("document.querySelectorAll('.resource-card').length >= 5")
        _open_resource(browser, "water")
        browser.evaluate(
            "document.getElementById('res-edit-amount').value = '100001'; "
            "document.getElementById('res-edit-save').click()"
        )
        browser.wait_for("document.querySelector('#modal-root .modal-overlay') !== null")
        stacking = browser.evaluate(
            """(() => {
              const confirm = document.querySelector('#modal-root .modal-overlay');
              const editor = document.getElementById('res-edit-modal');
              return {
                confirmZ: Number(getComputedStyle(confirm).zIndex),
                editorZ: Number(getComputedStyle(editor).zIndex),
                topIsConfirm: document.elementFromPoint(
                  innerWidth / 2, innerHeight / 2
                ).closest('#modal-root') !== null,
              };
            })()"""
        )
        assert stacking["confirmZ"] > stacking["editorZ"]
        assert stacking["topIsConfirm"] is True

        browser.evaluate("document.querySelector('#modal-root .btn-outline').click()")
        browser.wait_for("document.querySelector('#modal-root .modal-overlay') === null")
        assert browser.evaluate(
            "document.getElementById('res-edit-modal').style.display"
        ) == "flex"
        assert browser.evaluate(
            "document.querySelector('.resource-card[data-resource-type=\"water\"]').dataset.resourceAmount"
        ) == "10"

        browser.evaluate("document.getElementById('res-edit-save').click()")
        browser.wait_for("document.querySelector('#modal-root .btn-primary') !== null")
        browser.evaluate("document.querySelector('#modal-root .btn-primary').click()")
        browser.wait_for(
            "document.getElementById('res-edit-modal').style.display === 'none' && "
            "document.querySelector('.resource-card[data-resource-type=\"water\"]')"
            ".dataset.resourceAmount === '100001'"
        )
        source_state = browser.evaluate(
            """(() => {
              const card = document.querySelector(
                '.resource-card[data-resource-type="water"]'
              );
              return {
                source: card.dataset.resourceSource,
                remainingStatus: card.querySelector('.card-remaining').textContent,
              };
            })()"""
        )
        assert source_state["source"] == "estimate"
        assert source_state["remainingStatus"]
