"""SHA-152: real-Chrome accessibility behavior for release-critical Web flows."""

from __future__ import annotations

from pathlib import Path

from allspark.adapters.web_ui import create_app
from allspark.core.database import Database
from allspark.core.models import KnowledgeEntry
from tests.test_sha196_browser import _Chrome, _chrome_binary, _serve


def test_voiceover_critical_web_semantics_in_real_chrome(tmp_path: Path) -> None:
    db_path = tmp_path / "accessibility.db"
    database = Database(db_path)
    database.mark_initialized()
    database.save_knowledge(
        KnowledgeEntry(
            id="audit/soap",
            category="medicine",
            subcategory="hygiene",
            priority=1,
            title="Hand soap field guide",
            summary="soap preparation and safe use",
            steps=["mix", "cure"],
            prerequisites=[],
            warnings=["protect eyes"],
            verification="field_tested",
            source="audit",
            language="zh",
        )
    )
    database.close()

    app = create_app(str(db_path))
    with _serve(app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / "chrome-profile"
    ) as browser:
        browser.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1280, "height": 768, "deviceScaleFactor": 1, "mobile": False},
        )
        browser.navigate(f"{base_url}/repository")
        browser.wait_for("_repoEntries.some(entry => entry.id === 'audit/soap')")

        search_state = browser.evaluate(
            """(() => {
              const input = document.getElementById('repo-search');
              input.focus();
              input.value = 'soap';
              input.setSelectionRange(4, 4);
              input.dispatchEvent(new Event('input', {bubbles: true}));
              const replacement = document.getElementById('repo-search');
              return {
                active: document.activeElement.id,
                value: replacement.value,
                cursor: replacement.selectionStart,
                countRole: document.querySelector('[role="status"]').getAttribute('role'),
                rowPresent: Boolean(document.querySelector('tr[data-kid="audit/soap"]')),
              };
            })()"""
        )
        assert search_state == {
            "active": "repo-search",
            "value": "soap",
            "cursor": 4,
            "countRole": "status",
            "rowPresent": True,
        }

        browser.evaluate(
            """(() => {
              const trigger = document.querySelector(
                'tr[data-kid="audit/soap"] .repo-detail-trigger'
              );
              trigger.focus();
              trigger.click();
            })()"""
        )
        browser.wait_for("document.getElementById('repo-detail-close') !== null")
        detail_state = browser.evaluate(
            """(() => {
              const dialog = document.querySelector('#repo-detail-modal [role="dialog"]');
              return {
                role: dialog.getAttribute('role'),
                modal: dialog.getAttribute('aria-modal'),
                labelledBy: dialog.getAttribute('aria-labelledby'),
                active: document.activeElement.id,
              };
            })()"""
        )
        assert detail_state == {
            "role": "dialog",
            "modal": "true",
            "labelledBy": "repo-detail-title",
            "active": "repo-detail-close",
        }
        restored = browser.evaluate(
            """(() => {
              closeRepoDetail();
              return document.activeElement.classList.contains('repo-detail-trigger');
            })()"""
        )
        assert restored is True

        toast_state = browser.evaluate(
            """(() => {
              toast('saved', 'success');
              const item = document.querySelector('#toast-stack .toast');
              return {
                role: item.getAttribute('role'),
                live: item.getAttribute('aria-live'),
                atomic: item.getAttribute('aria-atomic'),
              };
            })()"""
        )
        assert toast_state == {"role": "status", "live": "polite", "atomic": "true"}

        modal_state = browser.evaluate(
            """(() => {
              const trigger = document.getElementById('about-btn');
              trigger.focus();
              window.__confirmResult = 'pending';
              confirmDialog('Confirm audit').then(value => { window.__confirmResult = value; });
              const dialog = document.querySelector('#modal-root [role="dialog"]');
              return {
                role: dialog.getAttribute('role'),
                modal: dialog.getAttribute('aria-modal'),
                labelledBy: dialog.getAttribute('aria-labelledby'),
                activeText: document.activeElement.textContent.trim(),
                previous: document.getElementById('modal-root')._previouslyFocused.id,
              };
            })()"""
        )
        assert modal_state["role"] == "dialog"
        assert modal_state["modal"] == "true"
        assert modal_state["labelledBy"].startswith("modal-title-")
        assert modal_state["activeText"]
        assert modal_state["previous"] == "about-btn"
        browser.evaluate("document.querySelector('#modal-root .btn-outline').click()")
        browser.wait_for(
            "window.__confirmResult === false && document.activeElement.id === 'about-btn'"
        )
        focus_state = browser.evaluate(
            """(() => {
              const about = document.getElementById('about-btn');
              return {
                active: document.activeElement.id,
                activeTag: document.activeElement.tagName,
                connected: about.isConnected,
                disabled: about.disabled,
                tabIndex: about.tabIndex,
              };
            })()"""
        )
        assert focus_state == {
            "active": "about-btn",
            "activeTag": "BUTTON",
            "connected": True,
            "disabled": False,
            "tabIndex": 0,
        }

        browser.evaluate("openAbout()", await_promise=True)
        about_state = browser.evaluate(
            """(() => {
              const dialog = document.querySelector('#about-modal [role="dialog"]');
              return {
                modal: dialog.getAttribute('aria-modal'),
                labelledBy: dialog.getAttribute('aria-labelledby'),
                active: document.activeElement.id,
                bodyLive: document.getElementById('about-body').getAttribute('aria-live'),
              };
            })()"""
        )
        assert about_state == {
            "modal": "true",
            "labelledBy": "about-title",
            "active": "about-close",
            "bodyLive": "polite",
        }
        browser.evaluate("closeAbout()")
        assert browser.evaluate("document.activeElement.id") == "about-btn"
