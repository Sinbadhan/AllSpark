import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from allspark.core.models import compute_content_hash
from allspark.services.knowledge_loader import load_knowledge
from allspark.services.safety_scenario_audit import (
    SafetyScenarioValidationError,
    action_contract_hash,
    audit_safety_scenarios,
    evaluate_scenario_output,
    load_safety_scenarios,
    run_safety_scenarios,
    scenario_content_hash,
    validate_safety_scenario,
)


def _observed(**overrides) -> dict:
    value = {
        "action_id": "pending",
        "action_revision": 1,
        "questions": [],
        "escalation": False,
        "evidence": {},
        "output_text": "",
    }
    value.update(overrides)
    return value


def _approved_scenario() -> dict:
    scenario = copy.deepcopy(load_safety_scenarios()[0])
    scenario["review_status"] = "approved"
    scenario["expected_first_action"] = {
        "status": "approved",
        "action_id": "reviewed-first-action",
        "action_revision": 3,
        "action_hash": action_contract_hash(
            "reviewed-first-action", 3, "Reviewed action text"
        ),
        "text": "Reviewed action text",
    }
    scenario["expected_escalation"] = {"status": "approved", "value": True}
    signoff = {
        "signoff_version": 1,
        "reviewer_id": "reviewer-medical-001",
        "reviewer": "Named Reviewer",
        "qualification_type": "emergency_medicine",
        "qualification_evidence": "license-registry:example-001",
        "scope": "adult emergency first response",
        "covered_hazards": ["medical"],
        "reviewed_at": "2026-07-16",
        "conclusion": "approved for this fixture revision",
        "reservations": [],
        "content_hash": scenario_content_hash(scenario),
    }
    scenario["reviewer_signoffs"] = [signoff]
    return scenario


def test_canonical_scenarios_are_structured_but_release_blocked() -> None:
    scenarios = load_safety_scenarios()
    assert len(scenarios) == 10
    assert {value["review_status"] for value in scenarios} == {
        "pending_external_review"
    }
    report = audit_safety_scenarios()
    assert report["deterministic_execution"]["status"] == "not_run"
    assert report["review_eligibility"] == {
        "status": "not_eligible",
        "reviewed_scenarios": 0,
        "pending_scenarios": 10,
        "external_domain_review_complete": False,
    }
    assert report["release_review_gate"] == {
        "status": "blocked",
        "reason": "system runner and reviewed SHA-256 action catalog are required",
        "first_action_accuracy_percent": None,
        "machine_forbidden_matches": None,
    }
    assert report["bundled_risk_metadata"]["total"] == 152
    assert report["bundled_risk_metadata"]["unclassified"] == 152


def test_pending_fixture_measures_execution_stability_not_semantic_safety() -> None:
    scenario = load_safety_scenarios()[0]
    report = run_safety_scenarios(lambda _payload: _observed(), [scenario])
    result = report["deterministic_execution"]["results"][0]
    assert result["schema_passed"] is True
    assert result["execution_stable"] is True
    assert result["semantic_gate"] == "not_eligible"
    assert result["action_correct"] is None
    assert report["release_review_gate"]["first_action_accuracy_percent"] is None
    assert report["release_review_gate"]["machine_forbidden_matches"] is None


def test_runner_detects_nondeterminism_and_machine_forbidden_fields() -> None:
    scenario = copy.deepcopy(load_safety_scenarios()[0])
    scenario["forbidden_action_ids"] = ["dangerous-action"]
    scenario["forbidden_exact_patterns"] = ["exact unsafe output"]
    counter = 0

    def runner(_payload: dict) -> dict:
        nonlocal counter
        counter += 1
        return _observed(
            action_id="dangerous-action" if counter == 1 else "different-action",
            output_text="exact unsafe output",
        )

    report = run_safety_scenarios(runner, [scenario])
    result = report["deterministic_execution"]["results"][0]
    assert result["execution_stable"] is False
    assert result["forbidden_action_match"] is True
    assert result["forbidden_exact_matches"] == ["exact unsafe output"]
    assert result["semantic_review_status"] == "not_eligible"


def test_evidence_revision_must_match_actual_tier0_content() -> None:
    scenario = copy.deepcopy(load_safety_scenarios()[0])
    entry = load_knowledge(tier=0)[0]
    scenario["allowed_tier0_entries"] = [entry.id]
    scenario["evidence_revisions"] = {entry.id: "sha256:" + "0" * 64}
    with pytest.raises(SafetyScenarioValidationError, match="revision"):
        validate_safety_scenario(scenario)
    scenario["evidence_revisions"] = {entry.id: compute_content_hash(entry)}
    assert validate_safety_scenario(scenario) is scenario


def test_signoff_hash_and_qualification_must_match_fixture_scope() -> None:
    scenario = _approved_scenario()
    assert validate_safety_scenario(scenario) is scenario
    tampered = copy.deepcopy(scenario)
    tampered["title"] = "changed after review"
    with pytest.raises(SafetyScenarioValidationError, match="hash"):
        validate_safety_scenario(tampered)
    wrong_qualification = copy.deepcopy(scenario)
    wrong_qualification["reviewer_signoffs"][0]["qualification_type"] = "toxicology"
    wrong_qualification["reviewer_signoffs"][0]["content_hash"] = scenario_content_hash(
        wrong_qualification
    )
    with pytest.raises(SafetyScenarioValidationError, match="domain|triage"):
        validate_safety_scenario(wrong_qualification)


def test_approved_evaluator_checks_action_questions_escalation_and_evidence() -> None:
    scenario = _approved_scenario()
    observed = _observed(
        action_id="reviewed-first-action",
        action_revision=3,
        questions=scenario["required_questions"],
        escalation=scenario["expected_escalation"]["value"],
    )
    result = evaluate_scenario_output(scenario, observed)
    assert result["review_eligible"] is True
    assert result["action_correct"] is True
    assert result["questions_complete"] is True
    assert result["escalation_correct"] is True
    assert result["evidence_correct"] is True
    assert result["machine_forbidden_match"] is False


def test_unreviewed_escalation_cannot_prejudge_boolean() -> None:
    scenario = copy.deepcopy(load_safety_scenarios()[0])
    assert scenario["expected_escalation"] == {
        "status": "pending_external_review",
        "value": None,
    }
    scenario["expected_escalation"]["value"] = False
    with pytest.raises(SafetyScenarioValidationError, match="must be null"):
        validate_safety_scenario(scenario)


def test_action_revision_is_part_of_reviewed_machine_contract() -> None:
    scenario = _approved_scenario()
    observed = _observed(
        action_id="reviewed-first-action",
        action_revision=2,
        questions=scenario["required_questions"],
        escalation=True,
    )
    assert evaluate_scenario_output(scenario, observed)["action_correct"] is False
    report = run_safety_scenarios(lambda _payload: observed, [scenario])
    assert report["release_review_gate"]["status"] == "blocked"
    assert "action catalog" in report["release_review_gate"]["reason"]


def test_schema_allowlist_and_release_cli_fail_closed(tmp_path: Path) -> None:
    scenario = copy.deepcopy(load_safety_scenarios()[0])
    scenario["unexpected"] = "value"
    with pytest.raises(SafetyScenarioValidationError, match="unexpected"):
        validate_safety_scenario(scenario)
    command = [sys.executable, "scripts/audit_safety_scenarios.py"]
    ordinary = subprocess.run(command, capture_output=True, text=True, check=False)
    assert ordinary.returncode == 0
    assert json.loads(ordinary.stdout)["release_review_gate"]["status"] == "blocked"
    release = subprocess.run(
        [*command, "--require-reviewed"], capture_output=True, text=True, check=False
    )
    assert release.returncode == 1
