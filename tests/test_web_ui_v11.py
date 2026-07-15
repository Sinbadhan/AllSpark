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

import pytest
from fastapi.testclient import TestClient

from allspark.adapters.web_ui import create_app
from allspark.core.database import Database
from allspark.infrastructure.hardware import FeatureFlags
from allspark.infrastructure.module_loader import ModuleRegistry
from allspark.services.power_monitor import PowerReading
from tests.assessment_helpers import confirmed_init_payload, valid_initial_assessment


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


def test_power_api_keeps_manual_measurements_and_soc_separate():
    with TempDb() as path:
        c = _client(path)
        manual = c.post("/api/power/manual?energy_wh=50")
        assert manual.status_code == 200
        reading = manual.json()["reading"]
        assert reading["energy_wh"] == 50
        assert reading["battery_percent"] is None
        assert reading["battery_percent_known"] is False
        assert reading["battery_percent_source"] is None
        assert reading["battery_percent_as_of"] is None
        assert reading["charging"] is None

        current = c.get("/api/power/status").json()["current"]
        assert current == reading

        explicit = c.post("/api/power/manual?energy_wh=50&charging=false").json()
        assert explicit["reading"]["charging"] is False


@pytest.mark.parametrize("invalid_soc", [float("nan"), -1.0, 101.0, float("inf")])
def test_power_api_never_serializes_invalid_trusted_soc(invalid_soc):
    with TempDb() as path:
        c = _client(path)
        monitor = c.app.state.container.get("power_monitor")
        monitor._current_reading = PowerReading(
            timestamp="2026-07-15T12:00:00+08:00",
            battery_percent=invalid_soc,
            battery_percent_source="trusted_bms",
            battery_percent_as_of="2026-07-15T12:00:00+08:00",
            battery_percent_trusted=True,
            source="battery_management_system",
        )

        response = c.get("/api/power/status")
        assert response.status_code == 200
        current = response.json()["current"]
        assert current["battery_percent"] is None
        assert current["battery_percent_known"] is False
        assert current["battery_percent_source"] is None
        assert current["battery_percent_as_of"] is None


@pytest.mark.parametrize("invalid_wh", ["nan", "inf", "-1"])
def test_power_manual_api_rejects_invalid_wh_without_writing(invalid_wh):
    with TempDb() as path:
        c = _client(path)
        before = c.get("/api/power/status").json()["current"]

        response = c.post(f"/api/power/manual?energy_wh={invalid_wh}")

        assert response.status_code == 422
        after = c.get("/api/power/status").json()["current"]
        assert after == before


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


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "water", "amount": "NaN"},
        {"type": "water", "amount": "Infinity"},
        {"type": "water", "amount": -1},
        {"type": "water", "amount": 10, "daily_consumption": -2},
    ],
)
def test_resource_post_rejects_invalid_values_without_writing(payload):
    with TempDb() as path:
        c = _client(path)
        before = c.get("/api/resources").json()
        response = c.post("/api/resources", json=payload)
        assert response.status_code == 422
        assert response.json()["status"] == "error"
        assert c.get("/api/resources").json() == before


def test_resource_api_exposes_field_certainty_people_provenance_and_time():
    with TempDb() as path:
        c = _client(path)
        response = c.post(
            "/api/resources",
            json={
                "type": "water",
                "amount": 12,
                "amount_known": True,
                "daily_consumption": 3,
                "consumption_known": True,
                "daily_intake": None,
                "intake_known": False,
                "people_count": 3,
                "as_of": "2026-07-15T12:00:00+08:00",
            },
        )
        assert response.status_code == 200
        water = next(item for item in c.get("/api/resources").json() if item["type"] == "water")
        assert water["unit"] == "L"
        assert water["amount_known"] is True
        assert water["consumption_known"] is True
        assert water["intake_known"] is False
        assert water["source"] == "user_input"
        assert water["source_label"] in {"User input", "用户输入"}
        assert water["as_of"] == "2026-07-15T12:00:00+08:00"
        assert water["people_count"] == 3
        assert water["amount_per_person"] == 4
        assert water["remaining_hours_per_person"] is None

        complete = c.post(
            "/api/resources",
            json={
                "type": "water",
                "amount": 12,
                "daily_consumption": 3,
                "daily_intake": 1,
                "people_count": 3,
                "input_kind": "estimate",
            },
        )
        assert complete.status_code == 200
        water = next(item for item in c.get("/api/resources").json() if item["type"] == "water")
        assert water["remaining_hours_per_person"] == 144
        assert water["source"] == "estimate"


def test_resource_api_rejects_spoofed_source_and_unconfirmed_outlier():
    with TempDb() as path:
        c = _client(path)
        before = c.get("/api/resources").json()
        spoof = c.post(
            "/api/resources",
            json={"type": "power", "amount": 100, "source": "sensor"},
        )
        assert spoof.status_code == 422
        invalid_kind = c.post(
            "/api/resources",
            json={"type": "power", "amount": 100, "input_kind": "sensor"},
        )
        assert invalid_kind.status_code == 422
        outlier = c.post(
            "/api/resources",
            json={"type": "water", "amount": 100_001},
        )
        assert outlier.status_code == 422
        assert c.get("/api/resources").json() == before

        confirmed = c.post(
            "/api/resources",
            json={"type": "water", "amount": 100_001, "confirm_outlier": True},
        )
        assert confirmed.status_code == 200


def test_storage_capacity_round_trip_and_nonstorage_rejection():
    with TempDb() as path:
        c = _client(path)
        storage = c.post(
            "/api/resources",
            json={
                "type": "storage",
                "amount": 80,
                "daily_consumption": 2,
                "daily_intake": 1,
                "capacity": 100,
                "capacity_known": True,
            },
        )
        assert storage.status_code == 200
        payload = next(item for item in c.get("/api/resources").json() if item["type"] == "storage")
        assert payload["capacity"] == 100
        assert payload["capacity_known"] is True

        nonstorage = c.post(
            "/api/resources",
            json={"type": "food", "amount": 10, "capacity": 20, "capacity_known": True},
        )
        assert nonstorage.status_code == 422


@pytest.mark.parametrize(
    "metadata",
    [
        {"people_count": True},
        {"people_count": 1.5},
        {"people_count": "2.0"},
        {"as_of": True},
        {"as_of": 123},
        {"as_of": {}},
        {"as_of": "2999-01-01T00:00:00Z"},
        {"input_kind": {}},
        {"source": {}},
    ],
)
def test_resource_api_malformed_metadata_returns_422_without_write(metadata):
    with TempDb() as path:
        c = _client(path)
        before = c.get("/api/resources").json()
        response = c.post(
            "/api/resources",
            json={"type": "water", "amount": 10, **metadata},
        )
        assert response.status_code == 422
        assert response.json()["status"] == "error"
        assert c.get("/api/resources").json() == before


def test_resource_api_localizes_fire_unit_without_changing_storage_unit():
    from allspark.core.i18n import set_language

    with TempDb() as path:
        c = _client(path)
        set_language("zh", persist=False)
        fire_zh = next(item for item in c.get("/api/resources").json() if item["type"] == "fire")
        assert fire_zh["unit"] == "uses"
        assert fire_zh["unit_label"] == "次"
        set_language("en", persist=False)
        fire_en = next(item for item in c.get("/api/resources").json() if item["type"] == "fire")
        assert fire_en["unit"] == "uses"
        assert fire_en["unit_label"] == "uses"
        set_language("zh", persist=False)


@pytest.mark.parametrize(
    ("resource_type", "field", "value"),
    [
        ("water", "amount", True),
        ("water", "amount", False),
        ("water", "daily_consumption", True),
        ("water", "daily_consumption", False),
        ("water", "daily_intake", True),
        ("water", "daily_intake", False),
        ("storage", "capacity", True),
        ("storage", "capacity", False),
    ],
)
def test_resource_api_rejects_boolean_numeric_fields_without_write(
    resource_type, field, value
):
    with TempDb() as path:
        c = _client(path)
        before = c.get("/api/resources").json()
        payload = {"type": resource_type, "amount": 10, field: value}
        if field == "capacity":
            payload["capacity_known"] = True
        response = c.post("/api/resources", json=payload)
        assert response.status_code == 422
        assert c.get("/api/resources").json() == before


def test_resource_api_exposes_unknown_finite_and_sustained_states():
    with TempDb() as path:
        c = _client(path)
        assert c.post(
            "/api/resources",
            json={"type": "power", "amount": 100, "daily_consumption": 10, "daily_intake": 10},
        ).status_code == 200
        assert c.post(
            "/api/resources",
            json={"type": "water", "amount": 12, "daily_consumption": 3, "daily_intake": 1},
        ).status_code == 200
        assert c.post(
            "/api/resources",
            json={"type": "storage", "amount": 80, "capacity": 100, "capacity_known": True},
        ).status_code == 200
        payload = {item["type"]: item for item in c.get("/api/resources").json()}
        assert payload["power"]["remaining_status"] == "sustained"
        assert payload["power"]["remaining_hours"] is None
        assert payload["water"]["remaining_status"] == "finite"
        assert payload["water"]["remaining_hours"] == 144
        assert payload["storage"]["remaining_status"] == "unknown"
        assert payload["storage"]["remaining_hours"] is None


def test_resource_web_contract_distinguishes_remaining_states_and_provenance():
    template = Path("allspark/templates/index.html").read_text(encoding="utf-8")
    assert 'remainingStatus = r.remaining_status || "unknown"' in template
    assert 'remainingStatus === "sustained"' in template
    assert "I18N.web_remaining_sustained" in template
    assert 'data-resource-source="${escHtml(String(r.source || \'\'))}"' in template
    assert 'role="group" aria-labelledby="res-edit-input-kind-label"' in template
    assert 'data-resource-input-kind="observed" aria-pressed="true"' in template
    assert 'data-resource-input-kind="estimate" aria-pressed="false"' in template
    assert ".q-chip:focus-visible" in template
    assert '<details id="res-edit-advanced"' in template
    assert 'data-resource-known-value="false" aria-pressed="true"' in template
    assert "resource-edit-actions" in template
    assert 'if (known !== true) input.value = ""' in template
    assert "RES_I18N.perPersonUnknown" in template
    assert "RES_I18N.valueRequired" in template
    assert template.index("modal._resourceType = rtype") < template.index(
        'setResourceFieldKnown("amount", amountKnown === true)'
    )


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
        assert body.get("redirect") == "/"

        # The init flag is gone from the DB.
        db = Database(path)
        try:
            assert db.is_initialized() is False
        finally:
            db.close()

        # And — the regression we are guarding against — `/` now renders
        # the init wizard, not the dashboard.
        html = c.get("/").text
        # SHA-221: reset returns to the language-first wizard, not the old
        # hardware-first flow or the dashboard.
        step_one = html.split('id="step-1"', 1)[1].split('id="step-2"', 1)[0]
        assert 'id="lang-zh"' in step_one
        assert 'id="lang-en"' in step_one


def test_l3_reset_client_uses_canonical_redirect():
    template = (
        Path(__file__).resolve().parents[1] / "allspark" / "templates" / "system.html"
    ).read_text()
    assert "window.location.assign(data.redirect)" in template


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


def test_reset_logs_api_exposes_accepted_and_rejected_web_attempts():
    with TempDb() as path:
        c = _client(path)
        accepted = c.post(
            "/api/reset/1", json={"confirm": True, "force": True}
        )
        assert accepted.status_code == 200

        rejected = c.post("/api/reset/2", json={"confirm": True})
        assert rejected.status_code == 409

        logs = c.get("/api/reset/logs").json()["logs"]
        assert [entry["status"] for entry in logs[:2]] == [
            "rejected",
            "accepted",
        ]
        assert all(entry["performed_by"] == "web" for entry in logs[:2])


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


@pytest.mark.parametrize(
    "language,message,expected_title",
    [
        ("zh", "用电池取火", "电池取火法"),
        ("en", "How to start a fire with a battery?", "Battery Fire Starting"),
    ],
)
def test_chat_keeps_specific_method_as_main_answer(
    language, message, expected_title
):
    with TempDb() as path:
        c = _client(path)
        response = c.post(
            "/api/chat", json={"message": message, "language": language}
        )
        assert response.status_code == 200
        entry_lines = re.findall(
            r"^\[[^\]]+\] (.+)$", response.json()["response"], re.MULTILINE
        )
        assert entry_lines
        assert entry_lines[0] == expected_title


def test_chat_does_not_fake_answer_for_unknown_specific_method():
    with TempDb() as path:
        c = _client(path)
        response = c.post(
            "/api/chat", json={"message": "如何用土豆生火", "language": "zh"}
        ).json()["response"]
        assert re.findall(r"^\[[^\]]+\] (.+)$", response, re.MULTILINE) == []
        assert "未能找到" in response


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


def test_system_page_uses_executable_reset_policy_descriptions():
    from allspark.services.reset_manager import get_reset_descriptions

    with TempDb() as path:
        c = _client(path)
        html = c.get("/system").text
        for description in get_reset_descriptions().values():
            assert description in html


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
            assert set(first["labels"]) == {"zh", "en"}
            assert all(first["labels"].values())


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
        assessment = {
            **valid_initial_assessment(),
            "shelter": {"status": "known", "value": "temporary_shelter"},
            "health": {"status": "known", "value": "minor_injury"},
            "urgency": {"status": "known", "value": "stable_but_urgent"},
            "threats": {
                "status": "selected",
                "values": ["extreme_weather", "wildlife"],
            },
        }
        r = c.post(
            "/api/init/complete",
            json=confirmed_init_payload(
                c,
                assessment=assessment,
                language="en",
                survivor_name="Test",
                location_type="wilderness",
                skills=["medical"],
            ),
        )
        assert r.status_code == 200, r.text
        db = Database(path)
        try:
            assert db.is_initialized() is True
            state = db.get_survivor_state()
            assert state.get("questionnaire_version") == "3"
            assert state.get("location_type") == "wilderness"
            assert state.get("shelter") == "temporary_shelter"
            assert "extreme_weather" in state.get("threats", "")
            assert state.get("skills") == "medical"
        finally:
            db.close()


def test_auth_cookie_and_one_time_bootstrap():
    """SHA-142: token out of HTML, httpOnly cookie auth, one-time bootstrap.

    - unauthed HTML -> redirect to /login; unauthed /api/* -> 401
    - token never appears in any HTML (login page or dashboard)
    - /api/auth/login exchanges the token for an httpOnly cookie
    - init/complete is one-time: 410 once initialized (re-init hijack blocked)
    """
    with TempDb() as path:
        db = Database(path)
        db.close()  # uninitialized

        token = "test-secret-token-xyz"
        client = TestClient(create_app(path, token=token))

        # 1. Unauthed HTML redirects to /login (303).
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 303, r.text
        assert r.headers["location"] == "/login"

        # 2. /login page is served and carries neither token nor the JS var.
        html = client.get("/login").text
        assert token not in html
        assert "const ALLSPARK_TOKEN" not in html

        # 3. Unauthed /api/* -> 401.
        assert client.get("/api/status").status_code == 401

        # 4. Wrong token rejected, no session established.
        assert client.post("/api/auth/login", json={"token": "wrong"}).status_code == 401
        assert client.get("/api/status").status_code == 401

        # 5. Correct token -> 200 + cookie; subsequent /api/* no longer 401
        #    (503 expected since the engine is not loaded pre-init).
        r = client.post("/api/auth/login", json={"token": token})
        assert r.status_code == 200, r.text
        assert client.get("/api/status").status_code != 401

        # 6. Bootstrap: init/complete works while not initialized (cookie-authed).
        init_payload = confirmed_init_payload(
            client,
            language="zh",
            survivor_name="T",
            skip_model=True,
        )
        r = client.post(
            "/api/init/complete",
            json=init_payload,
        )
        assert r.status_code == 200, r.text

        # 7. One-time: a second init/complete is rejected (410) even when authed.
        r = client.post(
            "/api/init/complete",
            json=init_payload,
        )
        assert r.status_code == 410, r.text
        assert r.json()["error"] == "bootstrap_closed"

        # 8. Dashboard HTML after auth+init still contains no token.
        html = client.get("/").text
        assert token not in html
        assert "const ALLSPARK_TOKEN" not in html


def test_bearer_header_still_accepted_for_api_clients():
    """SHA-142: Authorization: Bearer remains valid for programmatic API clients
    (cookie alternative). Wrong token rejected."""
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

        # Wrong token -> 401.
        r = client.get("/api/status", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401, r.text

        # Correct Bearer passes the gate (route may 503 in this fixture; the
        # point is the middleware did not block).
        r = client.get("/api/status", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code != 401, r.text

        # No Bearer, no cookie -> 401.
        assert client.get("/api/status").status_code == 401


def test_loopback_no_token_allows_init_and_blocks_reinit():
    """SHA-142: loopback (no token) keeps local trust but still enforces the
    one-time bootstrap gate on init/complete."""
    with TempDb() as path:
        db = Database(path)
        db.close()
        client = TestClient(create_app(path))  # no token -> loopback

        # First init succeeds.
        init_payload = confirmed_init_payload(
            client,
            language="zh",
            survivor_name="T",
            skip_model=True,
        )
        r = client.post("/api/init/complete", json=init_payload)
        assert r.status_code == 200, r.text

        # Second init blocked even on loopback.
        r = client.post("/api/init/complete", json={
            "language": "zh", "survivor_name": "T", "skip_model": True,
        })
        assert r.status_code == 410, r.text
