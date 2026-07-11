"""SHA-152: Web accessibility semantic checks.

Static assertions (a lightweight axe-equivalent) that interactive elements
use native button semantics, labels are associated, modals have dialog
semantics + Esc, and icon buttons expose aria-labels. Full VoiceOver/NVDA
manual verification remains a follow-up, but these guard the code-level
requirements against regression.
"""
from pathlib import Path

TEMPLATES = Path("allspark/templates")


def _read(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


class TestInitA11y:
    def test_language_cards_are_buttons_with_aria_pressed(self):
        t = _read("init.html")
        assert '<button type="button" class="lang-btn"' in t
        assert 'aria-pressed="false"' in t  # initial unselected state

    def test_chips_are_buttons_with_aria_pressed(self):
        t = _read("init.html")
        assert '<button type="button" class="q-chip' in t
        assert "aria-pressed=" in t  # set in chipField

    def test_selectlang_updates_aria_pressed(self):
        t = _read("init.html")
        assert 'setAttribute("aria-pressed", "true")' in t
        assert 'setAttribute("aria-pressed", "false")' in t


class TestIndexA11y:
    def test_configured_resource_card_is_keyboard_operable(self):
        t = _read("index.html")
        # The configured card (span-4, not offline) must carry role/tabindex so
        # it is operable after save, not just the unconfigured card.
        assert 'class="resource-card span-4" role="button" tabindex="0"' in t

    def test_modal_has_dialog_semantics(self):
        t = _read("index.html")
        assert 'role="dialog"' in t
        assert 'aria-modal="true"' in t
        assert 'aria-labelledby="res-edit-title"' in t

    def test_modal_labels_associated_with_inputs(self):
        t = _read("index.html")
        assert 'for="res-edit-amount"' in t
        assert 'for="res-edit-consumption"' in t
        assert 'for="res-edit-intake"' in t

    def test_modal_esc_handler_and_focus(self):
        t = _read("index.html")
        assert "Escape" in t  # Esc closes modal
        assert 'getElementById("res-edit-amount").focus()' in t  # focus on open


class TestBaseA11y:
    def test_icon_buttons_have_aria_labels(self):
        t = _read("base.html")
        assert 'aria-label="{{ t(\'web_notifications_title\') }}"' in t
        assert 'aria-label="{{ t(\'web_lang_switch_label\') }}"' in t
        assert 'aria-label="{{ t(\'web_about_title\') }}"' in t
        # SHA-156: the redundant settings icon (-> /config, dup of the nav
        # link) was removed; /config is reached via the nav link on all platforms.

    def test_icon_glyphs_are_aria_hidden(self):
        t = _read("base.html")
        assert 'aria-hidden="true"' in t

    def test_mobile_menu_buttons_have_aria_labels(self):
        t = _read("base.html")
        assert 'aria-label="{{ t(\'web_mobile_menu_open\') }}"' in t
        assert 'aria-label="{{ t(\'web_mobile_menu_close\') }}"' in t
