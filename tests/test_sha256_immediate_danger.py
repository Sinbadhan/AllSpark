from __future__ import annotations

import asyncio
import itertools
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import yaml
from fastapi.testclient import TestClient

from allspark.adapters import web_ui
from allspark.adapters.web_ui import create_app
from allspark.services import immediate_danger
from allspark.services.immediate_danger import (
    _action_hash,
    _source_hash,
    action_applies,
    assess_immediate_danger,
    load_action_catalog,
)


def _database_snapshot(app) -> tuple[str, ...]:
    """Stable schema + ordered row dump, not a row-count proxy."""
    return tuple(app.state.db.conn.iterdump())


def test_catalog_hashes_are_offline_rebuildable_contracts() -> None:
    catalog = load_action_catalog()
    assert catalog["review_status"] == "pending_external_review"
    assert catalog["release_eligible"] is False
    for source_id, source in catalog["sources"].items():
        assert source["content_hash"] == _source_hash(source_id, source)
        assert source["locator"]
        assert source["revision"]
        assert source["assertion"]
    for action in catalog["actions"]:
        assert action["content_hash"] == _action_hash(action)
        assert action["review_status"] == "pending_external_review"


def test_catalog_approval_path_requires_hashed_reviewer_coverage(
    monkeypatch, tmp_path: Path
) -> None:
    document = yaml.safe_load(
        immediate_danger.CATALOG_PATH.read_text(encoding="utf-8")
    )
    document["review_status"] = "approved"
    document["release_eligible"] = True
    for action in document["actions"]:
        action["review_status"] = "approved"
        action["content_hash"] = immediate_danger._action_hash(action)
    action_ids = [action["action_id"] for action in document["actions"]]
    document["reviewer_signoffs"] = [
        {
            "signoff_version": 1,
            "reviewer_id": "independent-panel-1",
            "reviewer": "Independent review panel",
            "qualification_type": "cross_domain_panel",
            "qualification_evidence": "Verified externally for this test fixture",
            "scope": "All catalog actions and both supported languages",
            "covered_action_ids": action_ids,
            "reviewed_at": "2026-07-17",
            "decision": "approved",
            "conclusion": "Approved test fixture",
            "reservations": [],
            "content_hash": "",
        }
    ]
    document["reviewer_signoffs"][0]["content_hash"] = (
        immediate_danger._catalog_hash(document)
    )
    path = tmp_path / "approved-catalog.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(immediate_danger, "CATALOG_PATH", path)
    load_action_catalog.cache_clear()
    try:
        catalog = load_action_catalog()
        assert catalog["release_eligible"] is True
        result = assess_immediate_danger({"threat_type": "none"}, "en")
        assert result["release_eligible"] is True

        document["reviewer_signoffs"][0]["covered_action_ids"] = action_ids[:-1]
        document["reviewer_signoffs"][0]["content_hash"] = (
            immediate_danger._catalog_hash(document)
        )
        path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        load_action_catalog.cache_clear()
        import pytest

        with pytest.raises(
            immediate_danger.ImmediateDangerValidationError,
            match="incomplete_action_coverage",
        ):
            load_action_catalog()
    finally:
        load_action_catalog.cache_clear()


def test_yaml_predicate_values_are_strings_and_fresh_process_loads() -> None:
    import yaml

    raw = yaml.safe_load(immediate_danger.CATALOG_PATH.read_text(encoding="utf-8"))
    accepted = [
        item
        for action in raw["actions"]
        for branch in action["applicable_when"]["any"]
        for values in branch.values()
        for item in values
    ]
    assert accepted
    assert all(isinstance(item, str) for item in accepted)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from allspark.services.immediate_danger import action_catalog_audit; "
            "assert action_catalog_audit()['action_count'] == 7",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_catalog_cache_clear_detects_tampered_hash(monkeypatch, tmp_path: Path) -> None:
    catalog_path = tmp_path / "action_catalog.yaml"
    text = immediate_danger.CATALOG_PATH.read_text(encoding="utf-8")
    catalog_path.write_text(text.replace("First Aid Steps", "Changed Aid Steps", 1), encoding="utf-8")
    monkeypatch.setattr(immediate_danger, "CATALOG_PATH", catalog_path)
    load_action_catalog.cache_clear()
    try:
        import pytest

        with pytest.raises(immediate_danger.ImmediateDangerValidationError, match="hash_mismatch"):
            load_action_catalog()
    finally:
        load_action_catalog.cache_clear()


def test_catalog_integrity_failure_is_503_not_user_422(
    monkeypatch, tmp_path: Path
) -> None:
    catalog_path = tmp_path / "tampered-action-catalog.yaml"
    catalog_path.write_text(
        immediate_danger.CATALOG_PATH.read_text(encoding="utf-8").replace(
            "First Aid Steps", "Tampered Aid Steps", 1
        ),
        encoding="utf-8",
    )
    app = create_app(str(tmp_path / "tampered.db"))
    client = TestClient(app)
    monkeypatch.setattr(immediate_danger, "CATALOG_PATH", catalog_path)
    load_action_catalog.cache_clear()
    try:
        for response in (
            client.get("/api/immediate-danger/catalog?language=zh"),
            client.post(
                "/api/immediate-danger/assess",
                json={"language": "zh", "facts": {"threat_type": "none"}},
            ),
        ):
            assert response.status_code == 503
            payload = response.json()
            assert payload["error"] == "immediate_danger_catalog_unavailable"
            assert payload["release_eligible"] is False
            assert "action" not in payload
            assert "content_hash" not in payload
            assert "hash_mismatch" not in payload["detail"]
    finally:
        load_action_catalog.cache_clear()


def test_missing_or_malformed_catalog_is_structured_503(
    monkeypatch, tmp_path: Path
) -> None:
    app = create_app(str(tmp_path / "load-failure.db"))
    client = TestClient(app)
    paths = [
        tmp_path / "missing.yaml",
        tmp_path / "malformed.yaml",
        tmp_path / "invalid-utf8.yaml",
    ]
    paths[1].write_text("actions: [unterminated", encoding="utf-8")
    paths[2].write_bytes(b"\xff\xfe\x00")
    original = immediate_danger.CATALOG_PATH
    try:
        for path in paths:
            monkeypatch.setattr(immediate_danger, "CATALOG_PATH", path)
            load_action_catalog.cache_clear()
            for response in (
                client.get("/api/immediate-danger/catalog"),
                client.post(
                    "/api/immediate-danger/assess",
                    json={"language": "en", "facts": {"threat_type": "none"}},
                ),
            ):
                assert response.status_code == 503
                assert response.json()["error"] == "immediate_danger_catalog_unavailable"
                assert response.json()["release_eligible"] is False
    finally:
        monkeypatch.setattr(immediate_danger, "CATALOG_PATH", original)
        load_action_catalog.cache_clear()


def test_missing_routed_action_is_catalog_integrity_503(
    monkeypatch, tmp_path: Path
) -> None:
    document = yaml.safe_load(
        immediate_danger.CATALOG_PATH.read_text(encoding="utf-8")
    )
    document["actions"] = [
        action
        for action in document["actions"]
        if action["action_id"] != "return-to-assessment"
    ]
    catalog_path = tmp_path / "missing-action.yaml"
    catalog_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    app = create_app(str(tmp_path / "missing-action.db"))
    client = TestClient(app)
    monkeypatch.setattr(immediate_danger, "CATALOG_PATH", catalog_path)
    load_action_catalog.cache_clear()
    try:
        response = client.post(
            "/api/immediate-danger/assess",
            json={"language": "en", "facts": {"threat_type": "none"}},
        )
        assert response.status_code == 503
        assert response.json()["error"] == "immediate_danger_catalog_unavailable"
        assert "action" not in response.json()
    finally:
        load_action_catalog.cache_clear()


def test_runtime_triage_does_not_access_network(monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise AssertionError("runtime network access is forbidden")

    monkeypatch.setattr("socket.socket", fail)
    monkeypatch.setattr("urllib.request.urlopen", fail)
    result = assess_immediate_danger(
        {"threat_type": "severe_bleeding", "scene_safe": "yes"}, "en"
    )
    assert result["action"]["action_id"] == "apply-direct-pressure"


def test_every_reachable_action_matches_machine_applicability() -> None:
    catalog = load_action_catalog()
    actions = {item["action_id"]: item for item in catalog["actions"]}
    fields = {
        "threat_type": immediate_danger._THREAT_TYPES,
        "scene_safe": immediate_danger._SCENE_STATES,
        "responsive": immediate_danger._RESPONSIVE_STATES,
        "breathing": immediate_danger._BREATHING_STATES,
        "communication": immediate_danger._COMMUNICATION_STATES,
    }
    for values in itertools.product(*(sorted(options) for options in fields.values())):
        facts = dict(zip(fields, values))
        result = assess_immediate_danger(facts, "en")
        if result["status"] == "action":
            action = actions[result["action"]["action_id"]]
            assert action_applies(action, facts), (facts, action["action_id"])


def test_question_options_have_fixed_risk_first_order() -> None:
    assert assess_immediate_danger({}, "en")["question"] == {
        "field": "threat_type",
        "options": [
            "fire_smoke_or_co",
            "severe_bleeding",
            "medical",
            "other",
            "none",
            "unknown",
        ],
    }
    assert assess_immediate_danger(
        {"threat_type": "medical"}, "en"
    )["question"]["options"] == ["yes", "no", "unknown"]


def test_distinct_medical_and_uncertain_routes_are_truthful() -> None:
    cases = [
        (
            {"threat_type": "other", "scene_safe": "yes"},
            "keep-distance-seek-local-help",
        ),
        (
            {"threat_type": "medical", "scene_safe": "yes", "responsive": "yes"},
            "seek-medical-assessment",
        ),
        (
            {
                "threat_type": "medical",
                "scene_safe": "yes",
                "responsive": "no",
                "breathing": "normal",
            },
            "seek-emergency-response",
        ),
        (
            {
                "threat_type": "medical",
                "scene_safe": "yes",
                "responsive": "yes",
                "breathing": "absent_or_abnormal",
            },
            "seek-emergency-response",
        ),
        (
            {
                "threat_type": "medical",
                "scene_safe": "yes",
                "responsive": "no",
                "breathing": "absent_or_abnormal",
            },
            "seek-emergency-response",
        ),
    ]
    for facts, action_id in cases:
        result = assess_immediate_danger(facts, "en")
        assert result["action"]["action_id"] == action_id
        assert result["release_eligible"] is False
        assert result["action"]["review_status"] == "pending_external_review"


def test_zh_action_display_contract_contains_no_raw_i18n_or_machine_keys() -> None:
    result = assess_immediate_danger(
        {"threat_type": "severe_bleeding", "scene_safe": "yes"}, "zh"
    )
    action = result["action"]
    displayed = [
        action["text"],
        *action["applicable_when_labels"],
        *action["contraindications"],
        action["escalation"],
        *(source["locator"] for source in action["sources"]),
    ]
    assert all("immediate_danger_" not in value for value in displayed)
    assert all("scene_safe" not in value for value in displayed)
    assert all(value.strip() for value in displayed)


def test_machine_applicability_branches_match_readable_conditions_one_to_one() -> None:
    for action in load_action_catalog()["actions"]:
        assert len(action["applicable_when"]["any"]) == len(
            action["applicable_label_keys"]
        )


def test_uninitialized_api_is_read_only_and_token_auth_is_not_bypassed(tmp_path: Path) -> None:
    app = create_app(str(tmp_path / "danger.db"))
    before = _database_snapshot(app)
    client = TestClient(app)
    response = client.post(
        "/api/immediate-danger/assess",
        json={
            "language": "zh",
            "facts": {"threat_type": "fire_smoke_or_co", "scene_safe": "yes"},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["action"]["action_id"] == "move-to-fresh-air"
    assert "已联系" not in payload["action"]["text"]
    assert app.state.initialized is False
    assert _database_snapshot(app) == before
    assert app.state.db.is_initialized() is False
    assert app.state.db.get_all_resources() == []

    protected = TestClient(create_app(str(tmp_path / "protected.db"), token="secret"))
    assert protected.get("/api/immediate-danger/catalog").status_code == 401
    assert protected.post(
        "/api/immediate-danger/assess",
        json={"facts": {"threat_type": "none"}},
    ).status_code == 401


def test_non_string_language_is_structured_422(tmp_path: Path) -> None:
    client = TestClient(create_app(str(tmp_path / "invalid-language.db")))
    for language in ([], {}):
        response = client.post(
            "/api/immediate-danger/assess",
            json={"language": language, "facts": {"threat_type": "none"}},
        )
        assert response.status_code == 422
        payload = response.json()
        assert payload["error"] == "invalid_immediate_danger_input"
        assert payload["errors"] == [
            {"field": "language", "code": "invalid_choice"}
        ]
        assert "action" not in payload


def test_blocked_hardware_detection_does_not_block_emergency_api(
    monkeypatch, tmp_path: Path
) -> None:
    entered = threading.Event()
    release = threading.Event()

    def blocked_detector():
        entered.set()
        release.wait(timeout=2)
        raise RuntimeError("detector unavailable")

    monkeypatch.setattr(web_ui, "detect_hardware", blocked_detector)
    app = create_app(str(tmp_path / "blocked-hardware.db"))

    async def exercise_same_event_loop() -> tuple[httpx.Response, httpx.Response, float]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            fallback_release = threading.Timer(1.0, release.set)
            fallback_release.start()
            started = time.monotonic()
            hardware_task = asyncio.create_task(client.get("/api/init/hardware"))
            # A synchronous detector in the async route blocks here until the
            # fallback timer, making the total exceed the latency boundary.
            await asyncio.sleep(0)
            emergency = await client.post(
                "/api/immediate-danger/assess",
                json={"language": "en", "facts": {"threat_type": "none"}},
            )
            elapsed = time.monotonic() - started
            assert entered.is_set()
            release.set()
            hardware = await hardware_task
            fallback_release.cancel()
            return emergency, hardware, elapsed

    response, hardware, elapsed = asyncio.run(exercise_same_event_loop())
    assert response.status_code == 200
    assert response.json()["action"]["action_id"] == "return-to-assessment"
    assert elapsed < 0.5
    assert hardware.status_code == 503
