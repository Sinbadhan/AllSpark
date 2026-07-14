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
        assert 'class="resource-card span-4" data-resource-type="' in t
        assert 'role="button" tabindex="0"' in t

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

    def test_modal_focus_trap_and_restore(self):
        t = _read("index.html")
        # SHA-152: focus trap (Tab cycles within modal) + restore on close.
        assert "_focusTrap" in t
        assert "_previouslyFocused" in t
        # Restore guards against a detached trigger (save path re-renders) via
        # document.body.contains before focusing; falls back to the same resource.
        assert "document.body.contains(prev)" in t
        assert "prev.focus()" in t
        assert 'getAttribute("data-resource-type") === resourceType' in t
        assert "await refreshDashboard()" in t

    def test_open_resource_edit_saves_explicit_trigger(self):
        t = _read("index.html")
        # SHA-152: openResourceEdit takes a `trigger` arg (passed as `this` from
        # onclick/onkeydown) so mouse clicks don't lose the trigger (was using
        # document.activeElement, which is <body> for mouse clicks).
        assert "function openResourceEdit(rtype, amount, consumption, intake, trigger)" in t
        assert "modal._previouslyFocused = trigger || document.activeElement" in t
        # All call sites pass `this`.
        assert t.count("openResourceEdit(") >= 5  # 1 def + 4 call sites
        assert ", this)" in t or ", this);" in t


class TestMobileNavA11y:
    def test_toggle_button_has_expanded_and_controls(self):
        t = _read("base.html")
        assert 'id="mobile-nav-toggle"' in t
        assert 'aria-expanded="false"' in t
        assert 'aria-controls="mobile-nav"' in t

    def test_overlay_has_dialog_semantics(self):
        t = _read("base.html")
        assert 'id="mobile-nav" class="mobile-nav-overlay" role="dialog"' in t
        assert 'aria-modal="true"' in t
        assert "web_nav_menu_label" in t

    def test_overlay_scrolls_at_high_zoom(self):
        t = _read("base.html")
        overlay_css = t.split(".mobile-nav-overlay {", 1)[1].split("}", 1)[0]
        assert "overflow-y: auto" in overlay_css
        assert "overscroll-behavior: contain" in overlay_css

    def test_toggle_function_isolates_and_traps(self):
        t = _read("base.html")
        assert "function toggleMobileNav(forceOpen)" in t
        assert "toggleAttribute('inert', willOpen)" in t  # background isolation
        assert 'setAttribute(\'aria-expanded\'' in t  # state sync
        assert "Escape" in t  # Esc closes
        assert "_trap" in t  # Tab trap

    def test_mobile_search_uses_central_close_path(self):
        t = _read("base.html")
        assert "toggleMobileNav(false)" in t
        assert 'nav.classList.remove("open")' not in t


class TestRepositoryA11y:
    def test_file_tree_button_has_distinct_label(self):
        t = _read("repository.html")
        # SHA-152: was web_mobile_menu_open ("打开菜单") - same as the global
        # mobile-menu button. Now a distinct file-tree label.
        assert "web_repository_file_tree_toggle" in t
        assert 'aria-label="{{ t(\'web_mobile_menu_open\') }}"' not in t

    def test_file_tree_button_syncs_expanded(self):
        t = _read("repository.html")
        assert 'id="file-tree-toggle"' in t
        assert 'aria-expanded="false"' in t
        assert 'aria-controls="file-tree"' in t
        assert "function toggleFileTree()" in t
        assert "setAttribute('aria-expanded'" in t


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
