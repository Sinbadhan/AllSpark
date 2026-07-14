"""SHA-227: Repository mobile scanning and file-tree keyboard behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from allspark.core.database import Database
from allspark.core.models import KnowledgeEntry
from tests.test_sha196_browser import _Chrome, _chrome_binary, _serve
from tests.test_web_ui_v11 import _client


def _seed_long_entries(path: Path) -> None:
    db = Database(path)
    db.mark_initialized()
    for language in ("zh", "en"):
        for index in range(25):
            db.save_knowledge(
                KnowledgeEntry(
                    id=f"audit/{language}/very-long-secondary-identifier-{index:02d}",
                    category="medicine",
                    subcategory="field-care",
                    priority=index % 3,
                    title=(
                        "移动端长标题急救与净水联合操作指南"
                        if language == "zh"
                        else "Long mobile field guide for first aid and water treatment"
                    ) + f" {index:02d}",
                    summary="scan-friendly summary",
                    verification="field_tested",
                    source="audit",
                    language=language,
                )
            )
    db.close()


def _layout_state(browser: _Chrome) -> dict:
    return browser.evaluate(
        """(() => {
          const root = document.documentElement;
          const content = document.getElementById('repo-content');
          const mobile = document.querySelector('.repo-mobile-list');
          const desktop = document.querySelector('.repo-desktop-table');
          const cards = Array.from(document.querySelectorAll('.repo-mobile-item'));
          const first = cards[0];
          return {
            viewport: innerWidth,
            pageFits: root.scrollWidth <= innerWidth + 1,
            contentFits: content.scrollWidth <= content.clientWidth + 1,
            mobileVisible: mobile && getComputedStyle(mobile).display !== 'none',
            desktopVisible: desktop && getComputedStyle(desktop).display !== 'none',
            cardCount: cards.length,
            firstFits: first ? first.scrollWidth <= first.clientWidth + 1 : false,
            title: first?.querySelector('.repo-mobile-title')?.textContent.trim() || '',
            category: first?.querySelector('[data-meta="category"]')?.textContent.trim() || '',
            verification: first?.querySelector('[data-meta="verification"]')?.textContent.trim() || '',
            id: first?.querySelector('.repo-mobile-id')?.textContent.trim() || '',
          };
        })()"""
    )


@pytest.mark.parametrize("language", ["zh", "en"])
def test_repository_responsive_scan_and_states(
    tmp_path: Path, language: str
) -> None:
    db_path = tmp_path / f"repository-{language}.db"
    _seed_long_entries(db_path)
    client = _client(str(db_path))
    client.post("/api/system/language", json={"language": language})

    with _serve(client.app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / f"chrome-profile-{language}"
    ) as browser:
        browser.navigate(f"{base_url}/repository")
        browser.wait_for("document.querySelectorAll('.repo-mobile-item').length > 0")
        query = "mobile field guide" if language == "en" else "移动端长标题"
        browser.evaluate(
            f"_repoFilters.lang = '{language}'; "
            f"_repoFilters.q = '{query}'; _repoRender();"
        )

        for width in (320, 390):
            browser.call(
                "Emulation.setDeviceMetricsOverride",
                {"width": width, "height": 844, "deviceScaleFactor": 1, "mobile": True},
            )
            state = _layout_state(browser)
            assert state["viewport"] == width
            assert state["pageFits"] is True
            assert state["contentFits"] is True
            assert state["mobileVisible"] is True
            assert state["desktopVisible"] is False
            assert state["cardCount"] > 0
            assert state["firstFits"] is True
            assert state["title"]
            assert state["category"]
            assert state["verification"]
            assert state["id"].startswith("audit/")

        browser.evaluate("_repoFilters.q = ''; _repoRender(); _repoGo(2)")
        assert _layout_state(browser)["cardCount"] > 0

        browser.evaluate("_repoFilters.q = 'no-such-repository-entry'; _repoRender()")
        empty = browser.evaluate(
            "document.querySelector('.repo-mobile-empty')?.textContent.trim()"
        )
        assert empty in {"无匹配条目", "No matching entries"}
        assert _layout_state(browser)["contentFits"] is True

        browser.evaluate("_repoFilters.q = ''; _repoRender()")
        for width in (768, 1280):
            browser.call(
                "Emulation.setDeviceMetricsOverride",
                {"width": width, "height": 844, "deviceScaleFactor": 1, "mobile": False},
            )
            state = _layout_state(browser)
            assert state["mobileVisible"] is False
            assert state["desktopVisible"] is True


def test_file_tree_is_native_and_keyboard_selectable(tmp_path: Path) -> None:
    path = tmp_path / "repository-tree.db"
    _seed_long_entries(path)
    client = _client(str(path))
    source = client.get("/repository").text
    assert 'onclick="showSection' not in source
    assert 'class="file-tree-item' in source
    assert ".file-tree-item:focus-visible" in source
    assert 'data-section="experience"' in source

    with _serve(client.app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / "chrome-profile-tree"
    ) as browser:
        browser.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1280, "height": 768, "deviceScaleFactor": 1, "mobile": False},
        )
        browser.navigate(f"{base_url}/repository")
        browser.wait_for("document.querySelector('.file-tree-item[aria-current]') !== null")
        initial = browser.evaluate(
            "Array.from(document.querySelectorAll('.file-tree-item[aria-current]')).map(b => b.dataset.section)"
        )
        assert initial == ["knowledge"]

        browser.evaluate(
            "document.querySelector('.file-tree-item[data-section=\"experience\"]').focus()"
        )
        assert browser.evaluate(
            "document.activeElement?.dataset.section"
        ) == "experience"
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
        browser.wait_for("currentSection === 'experience'")
        selected = browser.evaluate(
            "Array.from(document.querySelectorAll('.file-tree-item[aria-current]')).map(b => b.dataset.section)"
        )
        assert selected == ["experience"]

        browser.evaluate(
            "document.querySelector('.file-tree-item[data-section=\"models\"]').focus()"
        )
        browser.call(
            "Input.dispatchKeyEvent",
            {
                "type": "keyDown",
                "key": " ",
                "code": "Space",
                "text": " ",
                "windowsVirtualKeyCode": 32,
                "nativeVirtualKeyCode": 32,
            },
        )
        browser.call(
            "Input.dispatchKeyEvent",
            {
                "type": "keyUp",
                "key": " ",
                "code": "Space",
                "windowsVirtualKeyCode": 32,
                "nativeVirtualKeyCode": 32,
            },
        )
        browser.wait_for("currentSection === 'models'")
        selected = browser.evaluate(
            "Array.from(document.querySelectorAll('.file-tree-item[aria-current]')).map(b => b.dataset.section)"
        )
        assert selected == ["models"]
