"""P1-NEW-20260716-A: immediate danger stays reachable after initialization."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from allspark.adapters.web_ui import create_app
from allspark.core.database import Database
from allspark.core.i18n import set_language
from allspark.infrastructure.hardware import FeatureFlags
from allspark.infrastructure.module_loader import ModuleRegistry
from tests.test_sha196_browser import _Chrome, _chrome_binary, _serve
from tests.test_sha213_csp_browser import _assert_clean, _install_probe


def _initialized_app(path: Path, language: str):
    database = Database(path)
    try:
        database.finalize_initialization(language)
        ModuleRegistry(FeatureFlags()).save_to_db(database)
    finally:
        database.close()
    return create_app(str(path))


def _table_counts(path: Path) -> dict[str, int]:
    connection = sqlite3.connect(path)
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        return {
            table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in tables
        }
    finally:
        connection.close()


def _press(browser: _Chrome, key: str, *, shift: bool = False) -> None:
    modifiers = 8 if shift else 0
    for event_type in ("keyDown", "keyUp"):
        browser.call(
            "Input.dispatchKeyEvent",
            {
                "type": event_type,
                "key": key,
                "code": key,
                "text": "\r" if key == "Enter" and event_type == "keyDown" else "",
                "unmodifiedText": (
                    "\r" if key == "Enter" and event_type == "keyDown" else ""
                ),
                "windowsVirtualKeyCode": 13 if key == "Enter" else 9,
                "nativeVirtualKeyCode": 13 if key == "Enter" else 9,
                "modifiers": modifiers,
            },
        )


def _exercise_page(
    browser: _Chrome,
    url: str,
    expected_label: str,
    trigger_id: str,
) -> None:
    browser.navigate(url)
    browser.wait_for(f"document.getElementById({trigger_id!r})?.offsetParent !== null")
    entry = browser.evaluate(
        f"""(() => {{
          const button = document.getElementById({trigger_id!r});
          return {{
            tag: button.tagName,
            text: button.querySelector('span:last-child').textContent.trim(),
            name: button.getAttribute('aria-label'),
            hint: button.getAttribute('title'),
            iconHidden: button.querySelector('.material-symbols-outlined')
              .getAttribute('aria-hidden'),
          }};
        }})()"""
    )
    assert entry["tag"] == "BUTTON"
    assert entry["text"] == expected_label
    assert entry["name"] == expected_label
    assert entry["iconHidden"] == "true"
    assert entry["hint"] and entry["hint"] != expected_label

    storage_before = browser.evaluate("JSON.stringify({...localStorage})")
    browser.evaluate(
        """(() => {
          window.__immediateDangerWrites = [];
          const originalFetch = window.fetch.bind(window);
          window.fetch = (input, options = {}) => {
            const method = String(options.method || 'GET').toUpperCase();
            if (method !== 'GET') {
              window.__immediateDangerWrites.push({url: String(input), method});
            }
            return originalFetch(input, options);
          };
        })()"""
    )
    browser.evaluate(f"document.getElementById({trigger_id!r}).focus()")
    assert browser.evaluate("document.activeElement.id") == trigger_id
    _press(browser, "Enter")
    browser.wait_for("document.getElementById('danger-question-title') !== null")
    opened = browser.evaluate(
        """(() => ({
          active: document.activeElement.id,
          field: document.querySelector('[data-action="danger-choice"]').dataset.field,
          dialogHidden: document.getElementById('immediate-danger-dialog').classList.contains('hidden'),
          backgroundInert: document.querySelector('.main-wrapper').inert,
          atomic: document.getElementById('immediate-danger-content').getAttribute('aria-atomic'),
          live: document.getElementById('immediate-danger-content').getAttribute('aria-live'),
        }))()"""
    )
    assert opened == {
        "active": "danger-question-title",
        "field": "threat_type",
        "dialogHidden": False,
        "backgroundInert": True,
        "atomic": None,
        "live": "polite",
    }

    browser.evaluate(
        "document.querySelector('.danger-actions [data-action="
        "\"danger-close\"]').focus()"
    )
    _press(browser, "Tab")
    assert browser.evaluate("document.activeElement.id") == "immediate-danger-close"

    browser.evaluate(
        "document.querySelector('[data-action="
        "\"danger-choice\"][data-value=\"none\"]').click()"
    )
    browser.wait_for("document.querySelector('.danger-action') !== null")
    action = browser.evaluate(
        """(() => ({
          text: document.querySelector('.danger-action').textContent,
          ephemeral: document.querySelector('.danger-ephemeral').textContent,
        }))()"""
    )
    assert action["ephemeral"]
    assert "saved" in action["ephemeral"].lower() or "保存" in action["ephemeral"]

    browser.evaluate(
        "document.querySelector('.danger-actions [data-action="
        "\"danger-close\"]').click()"
    )
    closed = browser.evaluate(
        """(() => ({
          focus: document.activeElement.id,
          dialogHidden: document.getElementById('immediate-danger-dialog').classList.contains('hidden'),
          backgroundInert: document.querySelector('.main-wrapper').inert,
          contentEmpty: document.getElementById('immediate-danger-content').childElementCount === 0,
          storage: JSON.stringify({...localStorage}),
          writes: window.__immediateDangerWrites,
        }))()"""
    )
    assert closed["focus"] == trigger_id
    assert closed["dialogHidden"] is True
    assert closed["backgroundInert"] is False
    assert closed["contentEmpty"] is True
    assert closed["storage"] == storage_before
    assert closed["writes"]
    assert all(
        item == {"url": "/api/immediate-danger/assess", "method": "POST"}
        for item in closed["writes"]
    )

    browser.evaluate(f"document.getElementById({trigger_id!r}).click()")
    browser.wait_for("document.getElementById('danger-question-title') !== null")
    assert browser.evaluate(
        "document.querySelector('[data-action="
        "\"danger-choice\"]').dataset.field"
    ) == "threat_type"
    browser.evaluate("closeDanger()")
    _assert_clean(browser, url)


@pytest.mark.parametrize(
    ("language", "expected_label"),
    [("zh", "立即危险"), ("en", "Immediate danger")],
)
def test_immediate_danger_stays_reachable_across_product_lifecycle_in_chrome(
    tmp_path: Path,
    request,
    language: str,
    expected_label: str,
) -> None:
    request.addfinalizer(lambda: set_language("zh", persist=False))
    db_path = tmp_path / f"lifecycle-{language}.db"
    app = _initialized_app(db_path, language)
    before = _table_counts(db_path)

    with _serve(app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / f"chrome-lifecycle-{language}"
    ) as browser:
        _install_probe(browser)
        browser.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1280, "height": 844, "deviceScaleFactor": 1, "mobile": False},
        )
        for path in ("/", "/executions", "/repository"):
            _exercise_page(
                browser,
                base_url + path,
                expected_label,
                "immediate-danger-global-open",
            )

        browser.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 800, "height": 844, "deviceScaleFactor": 1, "mobile": False},
        )
        browser.navigate(base_url + "/executions")
        narrow_desktop = browser.evaluate(
            """(() => {
              const topbar = document.querySelector('.topbar');
              const entry = document.getElementById('immediate-danger-global-open');
              return {
                entryVisible: entry.offsetParent !== null,
                pageFits: document.documentElement.scrollWidth <= innerWidth + 1,
                topbarFits: topbar.scrollWidth <= topbar.clientWidth + 1,
              };
            })()"""
        )
        assert narrow_desktop == {
            "entryVisible": True,
            "pageFits": True,
            "topbarFits": True,
        }

        # Browser 200% reflow equivalent: 1280 physical px represented by a
        # 640 CSS px layout viewport at DPR 2. DPR 2 alone is not treated as zoom;
        # the 640 CSS px viewport is what exercises the reflow breakpoint.
        browser.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 640, "height": 422, "deviceScaleFactor": 2, "mobile": False},
        )
        _exercise_page(
            browser,
            base_url + "/executions",
            expected_label,
            "immediate-danger-mobile-open",
        )
        browser.evaluate("document.getElementById('immediate-danger-mobile-open').click()")
        browser.wait_for("document.getElementById('danger-question-title') !== null")
        zoom_reflow = browser.evaluate(
            """(() => {
              const topbar = document.querySelector('.mobile-topbar');
              const card = document.querySelector('.danger-dialog-card');
              const rect = card.getBoundingClientRect();
              return {
                cssWidth: innerWidth,
                dpr: devicePixelRatio,
                entryVisible: document.getElementById('immediate-danger-mobile-open')
                  .offsetParent !== null,
                pageFits: document.documentElement.scrollWidth <= innerWidth + 1,
                topbarFits: topbar.scrollWidth <= topbar.clientWidth + 1,
                cardFitsWidth: rect.left >= -1 && rect.right <= innerWidth + 1,
                cardFitsHeight: rect.top >= -1 && rect.bottom <= innerHeight + 1,
              };
            })()"""
        )
        assert zoom_reflow == {
            "cssWidth": 640,
            "dpr": 2,
            "entryVisible": True,
            "pageFits": True,
            "topbarFits": True,
            "cardFitsWidth": True,
            "cardFitsHeight": True,
        }
        browser.evaluate(
            "document.querySelector('.danger-actions [data-action="
            "\"danger-close\"]').click()"
        )
        assert browser.evaluate("document.activeElement.id") == (
            "immediate-danger-mobile-open"
        )

        browser.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 320, "height": 568, "deviceScaleFactor": 1, "mobile": True},
        )
        _exercise_page(
            browser,
            base_url + "/repository",
            expected_label,
            "immediate-danger-mobile-open",
        )
        mobile = browser.evaluate(
            """(() => ({
              pageFits: document.documentElement.scrollWidth <= innerWidth + 1,
              topbarFits: document.querySelector('.mobile-topbar').scrollWidth <=
                document.querySelector('.mobile-topbar').clientWidth + 1,
            }))()"""
        )
        assert mobile == {"pageFits": True, "topbarFits": True}

    assert _table_counts(db_path) == before
    assert app.state.db.is_initialized() is True


def test_immediate_danger_uses_one_shared_component_without_noisy_live_region() -> None:
    init = Path("allspark/templates/init.html").read_text(encoding="utf-8")
    base = Path("allspark/templates/base.html").read_text(encoding="utf-8")
    dialog = Path(
        "allspark/templates/partials/immediate_danger_dialog.html"
    ).read_text(encoding="utf-8")
    script = Path(
        "allspark/templates/partials/immediate_danger_script.html"
    ).read_text(encoding="utf-8")

    for template in (init, base):
        assert 'include "partials/immediate_danger_dialog.html"' in template
        assert 'include "partials/immediate_danger_script.html"' in template
    assert "/api/immediate-danger/assess" not in init
    assert "/api/immediate-danger/assess" not in base
    assert script.count("/api/immediate-danger/assess") == 1
    assert "localStorage" not in script
    assert 'aria-live="polite"' in dialog
    assert "aria-atomic" not in dialog
    assert "web_immediate_danger_global_button') }}\">" in base
    assert "web_immediate_danger_global_hint') }}\">" not in base
