"""SHA-152: Web accessibility semantic checks.

Static assertions (a lightweight axe-equivalent) that interactive elements
use native button semantics, labels are associated, modals have dialog
semantics + Esc, and icon buttons expose aria-labels. macOS VoiceOver evidence
is recorded for the release flow; Windows + NVDA remains a real-environment
follow-up. These checks guard the code-level requirements against regression.
"""
import re
from pathlib import Path

TEMPLATES = Path("allspark/templates")


def _read(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


class TestInitA11y:
    def test_language_cards_are_buttons_with_aria_pressed(self):
        t = _read("init.html")
        assert '<button type="button" class="language-button"' in t
        assert 'aria-pressed="false"' in t  # initial unselected state

    def test_critical_states_use_native_radios_and_fieldsets(self):
        t = _read("init.html")
        assert '<fieldset id="field-people_count">' in t
        assert 'type="radio" name="people-state"' in t
        assert 'type="radio" name="threat-state"' in t
        assert '<legend data-i18n="assessment_field_people_count">' in t

    def test_selectlang_updates_aria_pressed(self):
        t = _read("init.html")
        assert "setAttribute('aria-pressed',String(button.dataset.lang===lang))" in t
        assert "document.documentElement.lang=selectedLang" in t
        assert "document.title='ALLSPARK — '+tr('web_init_document_title')" in t

    def test_assessment_has_real_labels_error_summary_and_no_skip(self):
        t = _read("init.html")
        for field in ("health", "urgency", "shelter"):
            assert f'<label for="{field}"' in t
        assert 'id="init-errors" class="error-summary hidden" role="alert"' in t
        assert 'tabindex="-1"' in t
        assert "function errorFocusTarget(error)" in t
        assert "target?.focus()" in t
        assert "step-skip" not in t
        assert "fieldset" in t and "legend" in t

    def test_decorative_progress_and_document_title_stay_out_of_empty_vo_items(self):
        t = _read("init.html")
        assert '<ol class="progress" aria-hidden="true">' in t
        assert 'data-i18n-aria-label="web_init_progress_label"' not in t
        assert "web_init_document_title" in t
        assert "ALLSPARK — INIT" not in t


class TestIndexA11y:
    def test_configured_resource_card_is_keyboard_operable(self):
        t = _read("index.html")
        # The configured card (span-4, not offline) must carry role/tabindex so
        # it is operable after save, not just the unconfigured card.
        assert 'class="resource-card span-4" ' in t
        assert 'data-resource-type="${escHtml(String(r.type || \'\'))}"' in t
        assert 'data-index-action="resource-edit"' in t
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

    def test_resource_editor_uses_progressive_disclosure_and_known_segments(self):
        t = _read("index.html")
        assert '<details id="res-edit-advanced"' in t
        assert 'data-resource-known-field="amount"' in t
        assert 'data-resource-known-value="true"' in t
        assert 'data-resource-known-value="false"' in t
        assert 'role="group" aria-labelledby="res-edit-amount-label"' in t
        assert "resourceFieldKnown(\"amount\")" in t
        assert "type=\"checkbox\"" not in t

    def test_resource_editor_actions_are_sticky_and_dynamic_viewport_safe(self):
        t = _read("index.html")
        assert ".resource-edit-actions" in t
        assert 'if (known !== true) input.value = ""' in t
        assert "web_resource_per_person_unknown" in t
        assert "position: sticky" in t
        assert "max-height:calc(100dvh - 32px)" in t
        assert "scroll-padding-bottom:88px" in t
        assert 'getClientRects().length > 0' in t

    def test_modal_esc_handler_and_focus(self):
        t = _read("index.html")
        assert "Escape" in t  # Esc closes modal
        assert 'data-resource-input-kind][aria-pressed="true"]' in t

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

    def test_shared_confirmation_dialog_stacks_above_resource_editor(self):
        base = _read("base.html")
        index = _read("index.html")
        assert "z-index: 10000" in base
        assert "z-index:9999" in index

    def test_open_resource_edit_saves_explicit_trigger(self):
        t = _read("index.html")
        # SHA-152/SHA-213: delegated click/keyboard handlers pass their actual
        # data-action target, so mouse clicks do not fall back to <body> and the
        # CSP contract does not require inline `this` handlers.
        assert "function openResourceEdit(rtype, amount, consumption, intake," in t
        assert "modal._previouslyFocused = trigger || document.activeElement" in t
        assert "function openResourceFromTarget(target)" in t
        assert t.count("openResourceFromTarget(target)") >= 3
        assert "target,\n  );" in t
        assert 'data-resource-source="${escHtml(String(r.source || \'\'))}"' in t
        assert 'source === "estimate" ? "estimate" : "observed"' in t
        assert 'select:not([disabled])' in t


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

    def test_filter_controls_have_names_and_search_keeps_focus(self):
        t = _read("repository.html")
        for control in ("repo-search", "repo-f-cat", "repo-f-tier", "repo-f-ver", "repo-f-lang"):
            marker = t.split(f'id="{control}"', 1)[1].split(">", 1)[0]
            assert "aria-label=" in marker
        assert "replacement.focus({preventScroll: true})" in t
        assert "replacement.setSelectionRange(start, end)" in t

    def test_repository_rows_expose_native_detail_buttons(self):
        t = _read("repository.html")
        assert 'class="repo-detail-trigger' in t
        assert 'aria-label="${escHtml(REPO_I18N.detail_title' in t
        assert 'tabindex="0" data-kid=' not in t

    def test_repository_results_and_detail_are_announced(self):
        t = _read("repository.html")
        assert 'role="status" aria-live="polite" aria-atomic="true"' in t
        assert 'role="dialog" aria-modal="true" aria-labelledby="repo-detail-title"' in t
        assert 'document.getElementById("repo-detail-close").focus()' in t

    def test_repository_detail_traps_and_restores_focus(self):
        t = _read("repository.html")
        assert "_trapDialogTab(dialog, e)" in t
        assert "modal._previouslyFocused = document.activeElement" in t
        assert "document.body.contains(previous)" in t
        assert "previous.focus()" in t


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

    def test_primary_navigation_hides_decorative_icons(self):
        t = _read("base.html")
        nav = t.split("<!-- Mobile Nav Overlay -->", 1)[1].split("<!-- Main Content Wrapper -->", 1)[0]
        icon_tags = re.findall(r'<span class="material-symbols-outlined"[^>]*>', nav)
        assert len(icon_tags) >= 10
        assert all('aria-hidden="true"' in tag for tag in icon_tags)

    def test_toasts_are_live_regions_with_error_escalation(self):
        t = _read("base.html")
        assert "level === 'error' ? 'alert' : 'status'" in t
        assert "level === 'error' ? 'assertive' : 'polite'" in t
        assert "el.setAttribute('aria-atomic', 'true')" in t

    def test_generic_modals_have_dialog_semantics_and_focus_management(self):
        t = _read("base.html")
        assert "card.setAttribute('role', 'dialog')" in t
        assert "card.setAttribute('aria-modal', 'true')" in t
        assert "card.setAttribute('aria-labelledby', h.id)" in t
        assert "_trapDialogTab(card, e)" in t
        assert "r._previouslyFocused = document.activeElement" in t
        assert "document.body.contains(previous)" in t

    def test_about_modal_has_complete_dialog_behavior(self):
        t = _read("base.html")
        assert 'role="dialog" aria-modal="true" aria-labelledby="about-title"' in t
        assert 'id="about-body" class="text-sm" role="status" aria-live="polite"' in t
        assert 'document.getElementById("about-close").focus()' in t
        assert "_trapDialogTab(dialog, e)" in t
        assert "m._previouslyFocused = null" in t
