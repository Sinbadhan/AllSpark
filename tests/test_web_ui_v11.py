"""Web UI v1.1 (S1+S2+S3) regression tests.

Covers the platform-basics, survival-core, and full-feature surface added
between v1.0.0 and v1.0.1. Each test exercises a route through FastAPI's
TestClient against an isolated SQLite DB.

Critically also covers the L3 factory-reset state bug: after L3, the FastAPI
app must report itself as uninitialized so the UI returns the init wizard.
"""

import os
import re
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from allspark.adapters.web_ui import create_app
from allspark.core.database import Database
from allspark.infrastructure.hardware import FeatureFlags
from allspark.infrastructure.module_loader import ModuleRegistry


class TempDb:
    def __enter__(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        return self.path

    def __exit__(self, exc_type, exc, tb):
        if os.path.exists(self.path):
            os.unlink(self.path)


def _client(db_path: str) -> TestClient:
    """Boot an initialized AllSpark app rooted at db_path.

    Enables every feature flag we test against here. The default
    FeatureFlags() has everything off (PHANTOM tier), so weather,
    environment, psychology, reset_manager, etc. never get registered —
    that mismatch is fine in production (4 GB devices) but useless for
    UI regression tests.
    """
    db = Database(db_path)
    try:
        db.mark_initialized()
        flags = FeatureFlags(
            llm=True,
            image_recognition=True,
            voice_input=True,
            voice_output=True,
            web_ui=True,
            offline_map=True,
            kolibri=True,
            kiwix=True,
            multimodal=True,
            self_learning=True,
            governance=True,
            trade_engine=True,
            power_monitor=True,
            sensor_hub=True,
            data_preservation=True,
            boot_manager=True,
        )
        ModuleRegistry(flags).save_to_db(db)
    finally:
        db.close()
    return TestClient(create_app(db_path))


def test_local_icon_map_covers_static_template_icons():
    """Every static Material icon token must have an offline fallback glyph."""
    templates_dir = Path("allspark/templates")
    base_html = (templates_dir / "base.html").read_text(encoding="utf-8")
    map_match = re.search(r"const map = \{(?P<body>.*?)\n  \};", base_html, re.S)
    assert map_match is not None
    mapped = set(re.findall(r"\b([a-z][a-z0-9_]*)\s*:", map_match.group("body")))

    used: dict[str, set[str]] = {}
    icon_re = re.compile(
        r'<span[^>]*class="[^"]*material-symbols-outlined[^"]*"[^>]*>([^<]+)</span>'
    )
    for template in templates_dir.glob("*.html"):
        for raw_name in icon_re.findall(template.read_text(encoding="utf-8")):
            name = raw_name.strip()
            if re.fullmatch(r"[a-z0-9_]+", name):
                used.setdefault(name, set()).add(template.name)

    missing = {name: sorted(files) for name, files in used.items() if name not in mapped}
    assert not missing, f"Missing local icon fallback mappings: {missing}"


# ============================================================
# S1 — Platform basics
# ============================================================


def test_about_returns_version_and_flags():
    with TempDb() as path:
        c = _client(path)
        r = c.get("/api/system/about")
        assert r.status_code == 200
        data = r.json()
        assert data["version"]
        assert data["language"] in ("zh", "en")
        assert isinstance(data["feature_flags"], dict)
        assert "license" in data
        assert data["homepage"].startswith("http")


def test_language_switch_round_trip():
    with TempDb() as path:
        c = _client(path)
        # Switch en
        r = c.post("/api/system/language", json={"lang": "en"})
        assert r.status_code == 200
        assert r.json()["language"] == "en"
        # Topbar string follows the new language on next render
        html = c.get("/").text
        assert "Switch language" in html
        # Switch back
        r = c.post("/api/system/language", json={"lang": "zh"})
        assert r.json()["language"] == "zh"
        html = c.get("/").text
        assert "切换语言" in html


def test_language_rejects_unknown():
    with TempDb() as path:
        c = _client(path)
        r = c.post("/api/system/language", json={"lang": "fr"})
        assert r.json()["status"] == "error"


def test_personality_set_mode():
    with TempDb() as path:
        c = _client(path)
        r = c.post("/api/system/personality", json={"mode": "crisis"})
        assert r.status_code == 200
        assert r.json()["mode"] == "crisis"


def test_personality_rejects_unknown():
    with TempDb() as path:
        c = _client(path)
        r = c.post("/api/system/personality", json={"mode": "godmode"})
        assert r.json()["status"] == "error"


def test_operating_mode_set_persists():
    with TempDb() as path:
        c = _client(path)
        r = c.post("/api/system/operating-mode", json={"mode": "economy"})
        assert r.status_code == 200
        assert r.json()["mode"] == "economy"
        # Confirm via /api/status
        status = c.get("/api/status").json()
        assert status["mode"] in ("economy", "ECONOMY")  # normalized as enum value


def test_preserve_restore_requires_confirm_token():
    with TempDb() as path:
        c = _client(path)
        # Without confirm — must reject
        r = c.post("/api/preserve/restore?label=anything")
        body = r.json()
        assert body["status"] == "error"
        assert "confirm" in (body["error"] + body.get("detail", "")).lower()
        # Wrong token — must reject
        r = c.post("/api/preserve/restore?label=anything&confirm=YES")
        assert r.json()["status"] == "error"


def test_skf_path_traversal_still_blocked():
    """v1.0 security regression — must remain enforced after S1 changes."""
    with TempDb() as path:
        c = _client(path)
        for bad in ("/etc/passwd", "../../etc/passwd", "../etc/passwd"):
            r = c.get("/api/skf/info", params={"path": bad})
            # 400 from the path guard
            assert r.status_code == 400
            assert "must stay under" in r.text or "stay under" in r.text or "skf" in r.text.lower()


def test_module_disable_then_enable():
    with TempDb() as path:
        c = _client(path)
        # Try disabling a known-existent flag (image_recognition is in
        # FeatureFlags). The exact registry behavior depends on whether
        # the module is registered, but the endpoint must always respond
        # cleanly.
        for action in ("disable", "enable"):
            r = c.post(f"/api/modules/image_recognition/{action}")
            assert r.status_code == 200
            assert "module" in r.json()


# ============================================================
# S2 — Survival core
# ============================================================


def test_resource_post_accepts_full_payload():
    """The Web UI's resource edit modal sends amount + consumption + intake.
    Before S2, the route only forwarded `amount`."""
    with TempDb() as path:
        c = _client(path)
        r = c.post(
            "/api/resources",
            json={
                "type": "water",
                "amount": 12.5,
                "daily_consumption": 3.0,
                "daily_intake": 1.0,
            },
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        # Check it actually wrote all three fields
        resources = c.get("/api/resources").json()
        water = next(r for r in resources if r["type"] == "water")
        assert abs(water["amount"] - 12.5) < 0.01
        assert abs(water["daily_consumption"] - 3.0) < 0.01
        assert abs(water["daily_intake"] - 1.0) < 0.01


def test_briefing_endpoints_reachable():
    with TempDb() as path:
        c = _client(path)
        assert c.get("/api/briefing").status_code == 200
        assert c.get("/api/briefing/short").status_code == 200


def test_task_action_endpoint_responds():
    """An unknown task ID shouldn't 500; the action verb dispatch must work."""
    with TempDb() as path:
        c = _client(path)
        for action in ("start", "complete", "fail"):
            r = c.post(f"/api/tasks/T-NONEXISTENT/{action}")
            assert r.status_code == 200, f"{action}: {r.text}"
            assert r.json()["status"] in ("ok", "error")


def test_task_action_unknown_verb_400():
    with TempDb() as path:
        c = _client(path)
        r = c.post("/api/tasks/T-X/levitate")
        assert r.status_code == 400


def test_goal_add_and_complete():
    with TempDb() as path:
        c = _client(path)
        r = c.post("/api/goals/add", json={"description": "Find clean water", "title": "Water"})
        assert r.status_code == 200
        body = c.get("/api/goals").json()
        # Could be either a list (older) or {"goals": [...]} (current).
        goals = body.get("goals", body) if isinstance(body, dict) else body
        assert isinstance(goals, list)
        assert any(
            (g.get("description", "").startswith("Find clean") or g.get("title") == "Water")
            for g in goals if isinstance(g, dict)
        )


# ============================================================
# S3 — Full feature surface
# ============================================================


def test_psych_questions_and_assessment():
    with TempDb() as path:
        c = _client(path)
        qs = c.get("/api/psych/questions").json()["questions"]
        assert isinstance(qs, list) and len(qs) > 0
        # Submit zeros for every question
        answers = {q["id"]: 0 for q in qs}
        r = c.post("/api/psych/assessment", json={"answers": answers})
        assert r.status_code == 200


def test_psych_assessment_rejects_bad_payload():
    with TempDb() as path:
        c = _client(path)
        r = c.post("/api/psych/assessment", json={"answers": "not-a-dict"})
        assert r.json()["status"] == "error"


def test_weather_endpoints():
    with TempDb() as path:
        c = _client(path)
        r = c.get("/api/weather")
        assert r.status_code == 200
        body = r.json()
        assert "current" in body and "forecast" in body
        # Setting pressure should round-trip
        r = c.post("/api/weather/pressure", json={"pressure": 1013.5})
        assert r.json()["status"] == "ok"


def test_environment_endpoint():
    with TempDb() as path:
        c = _client(path)
        r = c.get("/api/environment")
        assert r.status_code == 200
        # Environment.assess() returns climate, terrain, threats,
        # opportunities, overall_score, recommendations.
        body = r.json()
        for dim in ("climate", "terrain", "threats", "opportunities"):
            assert dim in body


def test_map_poi_round_trip():
    with TempDb() as path:
        c = _client(path)
        # Empty initially
        assert c.get("/api/map/poi").json()["pois"] == []
        # Add one
        r = c.post(
            "/api/map/poi",
            json={"name": "North Well", "type": "water", "description": "spring"},
        )
        assert r.status_code == 200
        poi = r.json()["poi"]
        assert poi["name"] == "North Well"
        # List
        listed = c.get("/api/map/poi").json()["pois"]
        assert any(p["name"] == "North Well" for p in listed)
        # Delete
        r = c.delete(f"/api/map/poi/{poi['id']}")
        assert r.status_code == 200


def test_map_poi_requires_name():
    with TempDb() as path:
        c = _client(path)
        r = c.post("/api/map/poi", json={"type": "water"})
        assert r.json()["status"] == "error"


# ============================================================
# Critical state-machine bug: L3 reset must drop init flag
# ============================================================


def test_l3_factory_reset_returns_to_init_wizard():
    """After L3 the user must land on the init wizard, not the dashboard.

    The fix: /api/reset/3 re-syncs app.state.initialized from the DB row
    (which the reset itself wiped). Without it the in-memory flag stays
    True and `/` keeps rendering the dashboard.
    """
    with TempDb() as path:
        c = _client(path)
        # Confirm we start on the dashboard.
        html = c.get("/").text
        assert "{{ t(" not in html  # not raw template
        assert "PHASE" in html or "dashboard" in html.lower()

        # Execute L3 with both confirm and force.
        r = c.post("/api/reset/3", json={"confirm": True, "force": True})
        assert r.status_code == 200
        # The route's response wraps reset_manager's result.
        body = r.json()
        # success could be True or the error if cooldown is active
        assert body.get("success") is True or body.get("message") == "ok", body

        # The init flag is gone from the DB.
        db = Database(path)
        try:
            assert db.is_initialized() is False
        finally:
            db.close()

        # And — the regression we are guarding against — `/` now renders
        # the init wizard, not the dashboard.
        html = c.get("/").text
        # init.html contains the four-step wizard markup
        assert "wizard" in html.lower() or "web_init_step1_title" in html or "init-step" in html or "硬件检测" in html or "Hardware detection" in html


def test_l1_l2_reset_keeps_initialized():
    """L1/L2 must NOT reset the init flag — only L3 does."""
    with TempDb() as path:
        c = _client(path)
        for level in (1, 2):
            r = c.post(f"/api/reset/{level}", json={"confirm": True, "force": True})
            assert r.status_code == 200
            # Init wizard must NOT appear after L1/L2
            html = c.get("/").text
            assert "硬件检测" not in html and "Hardware detection" not in html, \
                f"L{level} reset should not return to init wizard"


def test_reset_requires_confirm():
    with TempDb() as path:
        c = _client(path)
        r = c.post("/api/reset/3", json={})
        assert r.json()["status"] == "error"
        # next_action carries the language-neutral "confirm=true" token in both zh/en
        assert "confirm=true" in r.json()["next_action"].lower()


def test_reset_invalid_level():
    with TempDb() as path:
        c = _client(path)
        r = c.post("/api/reset/9", json={"confirm": True})
        assert r.json()["status"] == "error"


# ============================================================
# Smoke: every page renders 200 with no template error
# ============================================================


def test_all_five_pages_render_200():
    with TempDb() as path:
        c = _client(path)
        for path_ in ("/", "/system", "/executions", "/config", "/repository"):
            r = c.get(path_)
            assert r.status_code == 200, f"{path_}: {r.status_code}"
            # No raw `{{ t(` markers — that would mean a missing key.
            assert "{{ t(" not in r.text, f"{path_}: unrendered i18n key"


def test_system_page_includes_new_cards():
    with TempDb() as path:
        c = _client(path)
        html = c.get("/system").text
        # S1
        assert "snapshot-list" in html  # backups card
        assert "confirmReset" in html   # danger zone card
        # S2
        assert "applyModes" in html     # mode control
        # S3
        assert "loc-gps" in html        # location card
        assert "comms-status" in html   # comms card
        assert "weather-current" in html
        assert "env-result" in html
        assert "moduleAction" in html   # module enable/disable column


def test_index_page_includes_new_tabs():
    with TempDb() as path:
        c = _client(path)
        html = c.get("/").text
        # S1
        assert "lang-toggle-btn" in html
        assert "openAbout" in html
        # S2
        assert "briefing-banner" in html
        assert "openResourceEdit" in html
        # S3
        assert "subtab-mind" in html
        assert "subtab-diary" in html


def test_executions_page_includes_tabs_and_actions():
    with TempDb() as path:
        c = _client(path)
        html = c.get("/executions").text
        assert "exectab-goals" in html
        assert "exectab-timeline" in html
        assert "taskAction" in html


def test_repository_page_skf_buttons_enabled():
    with TempDb() as path:
        c = _client(path)
        html = c.get("/repository").text
        # The S1 fix replaced `disabled` with onclick handlers.
        assert "openSkfExport" in html
        assert "openSkfImport" in html
        assert "renderCommunityPanel" in html


# ============================================================
# SHA-59 — Web UX: native dialogs replaced, CSS tokens resolve
# ============================================================


def test_templates_ship_no_native_alert_confirm_prompt():
    """SHA-59: no template may call native alert()/confirm()/prompt() — the
    project now uses an in-app toast/modal layer. Allowlist words like
    confirmDialog/promptDialog/alert_status must not trigger a false positive."""
    import re
    from pathlib import Path

    tmpl_dir = Path("allspark/templates")
    # Match a native call: `alert(`, `confirm(`, `prompt(` as a JS invocation.
    # Exclude the in-app confirmDialog/promptDialog helpers and i18n keys.
    native = re.compile(r"(?<![A-Za-z_])(alert|confirm|prompt)\s*\(")
    offenders = []
    for f in tmpl_dir.glob("*.html"):
        for i, line in enumerate(f.read_text().splitlines(), 1):
            # Skip i18n references and CSS/comment lines.
            stripped = line.strip()
            if stripped.startswith(("//", "/*", "*")):
                continue
            for m in native.finditer(line):
                # The lookbehind `(?<![A-Za-z_])` already excludes the call
                # being part of a longer identifier like `confirmDialog`/
                # `promptDialog`/`alert_status`.
                offenders.append(f"{f.name}:{i}: {line.strip()}")
    assert not offenders, "native dialogs still used:\n" + "\n".join(offenders)


def test_base_page_provides_toast_and_modal_infra():
    """SHA-59: the base template must define toast(), confirmDialog(),
    promptDialog() and the toast-stack/modal-root containers so children
    can drop native dialogs."""
    with TempDb() as path:
        c = _client(path)
        html = c.get("/").text
        assert "function toast(" in html
        assert "function confirmDialog(" in html
        assert "function promptDialog(" in html
        assert 'id="toast-stack"' in html
        assert 'id="modal-root"' in html


def test_templates_do_not_load_external_fonts_or_icons():
    """Offline-first UI must not depend on Google Fonts / Material Symbols CDN."""
    from pathlib import Path

    offenders = []
    for f in Path("allspark/templates").glob("*.html"):
        text = f.read_text()
        for token in ("fonts.googleapis.com", "fonts.gstatic.com", "Material Symbols"):
            if token in text:
                offenders.append(f"{f.name}: {token}")
    assert not offenders, "external font/icon dependencies remain:\n" + "\n".join(offenders)


def test_global_search_and_notifications_have_feedback_handlers():
    with TempDb() as path:
        c = _client(path)
        html = c.get("/").text
        assert 'id="global-search"' in html
        assert "runGlobalSearch" in html
        assert 'id="notifications-btn"' in html
        assert "showNotifications" in html
        assert "web_notifications_empty" in html


def test_system_network_degradation_is_human_readable():
    with TempDb() as path:
        c = _client(path)
        html = c.get("/system").text
        assert "web_comms_unavailable" in html
        assert "JSON.stringify(data, null, 2)" not in html


# ============================================================
# SHA-55 — Web UI / API contract drift
# ============================================================


def test_modules_api_returns_status_field():
    """/api/modules must return the `status` field (loaded|available|unsupported|
    disabled) plus `hw_supported`. The System page previously read the legacy
    `m.loaded / m.can_load` fields which the API never returned, making every
    module render as "disabled"."""
    with TempDb() as path:
        c = _client(path)
        mods = c.get("/api/modules").json()
        assert isinstance(mods, list)
        assert mods, "registry should expose at least one module"
        valid = {"loaded", "available", "unsupported", "disabled"}
        for m in mods:
            assert "status" in m, f"module {m.get('name')} missing `status`"
            assert m["status"] in valid, f"bad status {m['status']}"
            assert "hw_supported" in m
            assert "name" in m


def test_knowledge_category_entries_have_no_undefined_rendering():
    """The Repository knowledge table reads `e.category`, but
    /api/knowledge/category only returns id/title/summary/priority. The
    frontend now re-tags the category. Assert the raw API contract and that
    the page render does not leak a literal `undefined` token in the table."""
    with TempDb() as path:
        c = _client(path)
        cats = c.get("/api/knowledge/categories").json()
        assert cats, "knowledge base should expose categories"
        cat = cats[0]["category"]
        entries = c.get(f"/api/knowledge/category/{cat}").json()
        assert entries, f"category {cat} should have entries"
        for e in entries:
            # Contract: id/title/summary/priority. `category` is intentionally
            # not per-entry; the UI derives it from the requested category.
            assert {"id", "title", "summary", "priority"} <= set(e.keys())
        # Repository page must not render the string "undefined" in its body.
        html = c.get("/repository").text
        assert "undefined" not in html


# ============================================================
# SHA-56 — Structured init questionnaire (CLI path + Web fields)
# ============================================================


def test_init_questionnaire_endpoint_loads_yaml():
    """/api/init/questionnaire must surface the structured options from
    allspark/data/questionnaire.yaml. The CLI wizard previously read the wrong
    path (adapters/data/) and silently degraded to free-text."""
    with TempDb() as path:
        c = _client(path)
        data = c.get("/api/init/questionnaire").json()
        assert data["version"] == "2"
        q = data["questions"]
        # The YAML ships these option groups (PRD §4.2.2).
        for key in ("location_types", "shelter_statuses", "threat_types",
                    "skill_categories", "urgency_levels", "health_statuses"):
            assert key in q, f"missing questionnaire group {key}"
            assert q[key], f"{key} has no options"
            first = q[key][0]
            assert "key" in first and "label_key" in first


def test_init_wizard_cli_loads_questionnaire_from_correct_path():
    """The CLI loader must resolve to allspark/data/questionnaire.yaml, not the
    non-existent adapters/data/ path (SHA-56)."""
    from allspark.adapters.init_wizard import _load_questionnaire

    q = _load_questionnaire()
    assert q, "questionnaire YAML failed to load — path is wrong"
    assert "location_types" in q and len(q["location_types"]) >= 6


def test_init_complete_accepts_questionnaire_json_body():
    """/api/init/complete must accept a JSON body carrying the structured
    questionnaire and persist questionnaire_version + the key fields."""
    with TempDb() as path:
        # Boot an uninitialized app rooted at a fresh DB.
        db = Database(path)
        db.close()
        c = TestClient(create_app(path))
        r = c.post("/api/init/complete", json={
            "language": "en",
            "survivor_name": "Test",
            "location_type": "wilderness",
            "shelter": "temporary_shelter",
            "health": "minor",
            "urgency": "urgent",
            "threats": ["extreme_weather", "wildlife"],
            "skills": ["medical"],
        })
        assert r.status_code == 200, r.text
        db = Database(path)
        try:
            assert db.is_initialized() is True
            state = db.get_survivor_state()
            assert state.get("questionnaire_version") == "2"
            assert state.get("location_type") == "wilderness"
            assert state.get("shelter") == "temporary_shelter"
            assert "extreme_weather" in state.get("threats", "")
            assert state.get("skills") == "medical"
        finally:
            db.close()


def test_bearer_token_middleware_protects_non_init_api():
    """Non-loopback binding (token set) gates /api/* with Bearer auth (audit H3).

    - /api/init/* stays open (init wizard must work pre-auth)
    - other /api/* return 401 without a valid Bearer token
    - correct Bearer token passes the middleware
    - HTML pages receive the token via api_token context for the fetch wrapper
    """
    with TempDb() as path:
        db = Database(path)
        try:
            db.mark_initialized()
            flags = FeatureFlags(llm=True, web_ui=True)
            ModuleRegistry(flags).save_to_db(db)
        finally:
            db.close()

        token = "test-secret-token-xyz"
        client = TestClient(create_app(path, token=token))

        # /api/init/* is exempt — init wizard works before auth
        assert client.get("/api/init/status").status_code == 200

        # /api/status (non-init) requires the token
        r = client.get("/api/status")
        assert r.status_code == 401, r.text
        assert r.json()["error"] == "unauthorized"

        # Wrong token rejected
        r = client.get("/api/status", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401, r.text

        # Correct token passes the middleware (route may still 503 if the
        # engine isn't fully loaded in this minimal fixture — the point is
        # the middleware did not block)
        r = client.get("/api/status", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code != 401, r.text

        # HTML pages inject the token so the browser fetch wrapper can use it
        html = client.get("/").text
        assert f'const ALLSPARK_TOKEN = "{token}"' in html
