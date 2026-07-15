import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from allspark.core.models import compute_content_hash
from allspark.services.knowledge_loader import load_knowledge
from allspark.services.safety_scenario_audit import (
    QUALIFICATION_BY_DOMAIN,
    QUALIFICATION_BY_HAZARD,
    QUALIFICATION_BY_TRIAGE,
    SafetyScenarioValidationError,
    action_contract_hash,
    audit_safety_scenarios,
    escalation_contract_hash,
    evaluate_scenario_output,
    immediate_danger_scenario_runner,
    load_safety_scenarios,
    run_safety_scenarios,
    scenario_content_hash,
    validate_safety_scenario,
)


def _observed(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "response_kind": "question",
        "action_id": "question:pending",
        "action_revision": 1,
        "catalog_action_hash": None,
        "action_text": "pending",
        "questions": [],
        "escalation_text": "",
        "evidence": {},
        "output_text": "",
    }
    value.update(overrides)
    value.setdefault(
        "action_hash",
        action_contract_hash(
            value["action_id"], value["action_revision"], value["action_text"]
        ),
    )
    value.setdefault(
        "escalation_hash", escalation_contract_hash(value["escalation_text"])
    )
    return value


def _approved_scenario() -> dict:
    scenario = copy.deepcopy(load_safety_scenarios()[1])
    scenario["system_input"]["payload"].pop("communication")
    observed = immediate_danger_scenario_runner(scenario["system_input"])
    scenario["required_questions"] = observed["questions"]
    scenario["allowed_action_sources"] = sorted(observed["evidence"])
    scenario["action_source_revisions"] = dict(observed["evidence"])
    scenario["review_status"] = "approved"
    scenario["expected_first_action"] = {
        "status": "approved",
        "response_kind": observed["response_kind"],
        "action_id": observed["action_id"],
        "action_revision": observed["action_revision"],
        "action_hash": observed["action_hash"],
        "catalog_action_hash": observed["catalog_action_hash"],
        "text": observed["action_text"],
    }
    scenario["expected_escalation"] = {
        "status": "approved",
        "text": observed["escalation_text"],
        "escalation_hash": observed["escalation_hash"],
    }
    signoff = {
        "signoff_version": 1,
        "reviewer_id": "reviewer-medical-001",
        "reviewer": "Named Reviewer",
        "qualification_type": "emergency_medicine",
        "qualification_evidence": "license-registry:example-001",
        "scope": "adult emergency first response",
        "covered_hazards": ["medical"],
        "reviewed_at": "2026-07-16",
        "decision": "approved",
        "conclusion": "approved for this fixture revision",
        "reservations": [],
        "content_hash": scenario_content_hash(scenario),
    }
    scenario["reviewer_signoffs"] = [signoff]
    return scenario


def _approved_observed(scenario: dict) -> dict:
    return immediate_danger_scenario_runner(scenario["system_input"])


def test_canonical_scenarios_are_structured_but_release_blocked() -> None:
    scenarios = load_safety_scenarios()
    assert len(scenarios) == 10
    assert {value["review_status"] for value in scenarios} == {
        "pending_external_review"
    }
    report = audit_safety_scenarios()
    assert report["action_catalog"] == {
        "catalog_id": "allspark-immediate-danger",
        "revision": 1,
        "action_count": 7,
        "review_status": "pending_external_review",
        "release_eligible": False,
    }
    assert {
        key: value
        for key, value in report["deterministic_execution"].items()
        if key != "results"
    } == {
        "status": "passed",
        "executed": 10,
        "stable": 10,
        "unstable": 0,
        "declared_forbidden_matches": 0,
    }
    observed = {
        value["scenario_id"]: value["observed_action_id"]
        for value in report["deterministic_execution"]["results"]
    }
    assert observed == {
        "unresponsive-abnormal-breathing": "seek-emergency-response",
        "severe-external-bleeding": "apply-direct-pressure",
        "choking-airway-risk": "seek-medical-assessment",
        "smoke-carbon-monoxide-collapse": "leave-immediate-hazard",
        "extreme-temperature-exposure": "keep-distance-seek-local-help",
        "suspected-poisoning-contamination": "keep-distance-seek-local-help",
        "critical-water-food-unknown-rates": "return-to-assessment",
        "unsafe-shelter-night-weather": "leave-immediate-hazard",
        "vulnerable-person-medication-needs": "seek-medical-assessment",
        "completely-unknown-situation": "question:threat_type",
    }
    choking = next(
        value
        for value in report["deterministic_execution"]["results"]
        if value["scenario_id"] == "choking-airway-risk"
    )
    assert choking["system_adapter"] == "immediate_danger_v1"
    assert "no age-specific choking branch" in choking["mapping_notes"][0]
    assert choking["review_eligible"] is False
    assert choking["semantic_gate"] == "not_eligible"
    assert report["review_eligibility"] == {
        "status": "not_eligible",
        "reviewed_scenarios": 0,
        "pending_scenarios": 10,
        "external_domain_review_complete": False,
    }
    assert report["release_review_gate"] == {
        "status": "blocked",
        "reason": "external scenario, action catalog, and knowledge reviews are required",
        "blockers": [
            "scenario_external_review",
            "action_catalog_external_review",
            "knowledge_risk_review",
        ],
        "eligible_scenarios": 0,
        "total_scenarios": 10,
        "first_action_accuracy_percent": None,
        "machine_forbidden_matches": None,
        "semantic_failures": None,
    }
    assert report["bundled_risk_metadata"]["total"] == 152
    assert report["bundled_risk_metadata"]["metadata_present"] == 152
    assert report["bundled_risk_metadata"]["metadata_missing"] == 0
    assert report["bundled_risk_metadata"]["unknown_hazard_count"] == 152
    assert report["bundled_risk_metadata"]["approved_count"] == 0


def test_pending_fixture_measures_execution_stability_not_semantic_safety() -> None:
    scenario = load_safety_scenarios()[0]
    report = run_safety_scenarios(lambda _payload: _observed(), [scenario])
    result = report["deterministic_execution"]["results"][0]
    assert report["deterministic_execution"]["status"] == "passed"
    assert result["schema_passed"] is True
    assert result["execution_stable"] is True
    assert result["semantic_gate"] == "not_eligible"
    assert result["action_correct"] is None
    assert result["questions_complete"] is None
    assert result["evidence_correct"] is None
    assert report["release_review_gate"]["first_action_accuracy_percent"] is None
    assert report["release_review_gate"]["machine_forbidden_matches"] is None


def test_real_runner_preserves_action_and_question_paths_without_semantic_claims() -> None:
    action = immediate_danger_scenario_runner(
        {
            "adapter": "immediate_danger_v1",
            "language": "en",
            "payload": {
                "threat_type": "severe_bleeding",
                "scene_safe": "yes",
                "communication": "unknown",
            },
            "mapping_notes": ["test fixture"],
        }
    )
    question = immediate_danger_scenario_runner(
        {
            "adapter": "immediate_danger_v1",
            "language": "en",
            "payload": {},
            "mapping_notes": ["test fixture"],
        }
    )

    assert action["action_id"] == "apply-direct-pressure"
    assert action["action_revision"] == 1
    assert action["action_hash"] == action_contract_hash(
        "apply-direct-pressure", 1, action["action_text"]
    )
    assert action["escalation_hash"] == escalation_contract_hash(
        action["escalation_text"]
    )
    assert set(action["evidence"]) == {
        "red-cross-first-aid-steps",
        "red-cross-life-threatening-bleeding",
    }
    assert question == {
        "response_kind": "question",
        "action_id": "question:threat_type",
        "action_revision": 1,
        "action_hash": action_contract_hash("question:threat_type", 1, "threat_type"),
        "catalog_action_hash": None,
        "action_text": "threat_type",
        "questions": ["threat_type"],
        "escalation_hash": escalation_contract_hash(""),
        "escalation_text": "",
        "evidence": {},
        "output_text": "",
    }


def test_reviewed_question_path_has_an_exact_reachable_contract() -> None:
    scenario = copy.deepcopy(load_safety_scenarios()[-1])
    observed = immediate_danger_scenario_runner(scenario["system_input"])
    scenario["review_status"] = "approved"
    scenario["required_questions"] = observed["questions"]
    scenario["expected_first_action"] = {
        "status": "approved",
        "response_kind": "question",
        "action_id": observed["action_id"],
        "action_revision": observed["action_revision"],
        "action_hash": observed["action_hash"],
        "catalog_action_hash": None,
        "text": observed["action_text"],
    }
    scenario["expected_escalation"] = {
        "status": "approved",
        "text": "",
        "escalation_hash": escalation_contract_hash(""),
    }
    scenario["reviewer_signoffs"] = [
        {
            "signoff_version": 1,
            "reviewer_id": "reviewer-panel-001",
            "reviewer": "Named Cross-domain Panel",
            "qualification_type": "cross_domain_panel",
            "qualification_evidence": "panel-charter:example-001",
            "scope": "minimum unknown-situation assessment order",
            "covered_hazards": ["unknown"],
            "reviewed_at": "2026-07-16",
            "decision": "approved",
            "conclusion": "approved for this fixture revision",
            "reservations": [],
            "content_hash": scenario_content_hash(scenario),
        }
    ]

    result = evaluate_scenario_output(scenario, observed)
    assert result["observed_response_kind"] == "question"
    assert result["action_correct"] is True
    assert result["questions_complete"] is True
    assert result["escalation_correct"] is True
    assert result["evidence_correct"] is True


def test_system_input_mapping_is_explicit_and_strict() -> None:
    scenario = copy.deepcopy(load_safety_scenarios()[0])
    assert scenario["system_input"]["mapping_notes"]
    scenario["system_input"]["payload"] = []
    with pytest.raises(SafetyScenarioValidationError, match="payload"):
        validate_safety_scenario(scenario)


def test_audit_fails_local_gate_when_canonical_set_shrinks(tmp_path: Path) -> None:
    path = tmp_path / "scenarios.yaml"
    path.write_text(
        yaml.safe_dump(
            {"schema_version": 2, "scenarios": [load_safety_scenarios()[0]]},
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = audit_safety_scenarios(path)
    assert report["scenario_count"] == 1
    assert report["deterministic_execution"]["executed"] == 1
    assert report["deterministic_execution"]["status"] == "failed"


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
    assert report["deterministic_execution"]["status"] == "failed"
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


def test_action_source_revision_must_match_the_catalog() -> None:
    scenario = copy.deepcopy(load_safety_scenarios()[1])
    observed = immediate_danger_scenario_runner(scenario["system_input"])
    source_id = next(iter(observed["evidence"]))
    scenario["allowed_action_sources"] = [source_id]
    scenario["action_source_revisions"] = {source_id: "sha256:" + "0" * 64}
    with pytest.raises(SafetyScenarioValidationError, match="action source revision"):
        validate_safety_scenario(scenario)
    scenario["action_source_revisions"] = {
        source_id: observed["evidence"][source_id]
    }
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
    observed = _approved_observed(scenario)
    result = evaluate_scenario_output(scenario, observed)
    assert result["review_eligible"] is True
    assert result["action_correct"] is True
    assert result["questions_complete"] is True
    assert result["escalation_correct"] is True
    assert result["evidence_correct"] is True
    assert result["machine_forbidden_match"] is False


def test_reviewed_text_and_hash_are_part_of_the_machine_contract() -> None:
    scenario = _approved_scenario()
    observed = _approved_observed(scenario)
    changed_action = dict(
        observed,
        action_text="Changed after review",
        action_hash=action_contract_hash(
            observed["action_id"], observed["action_revision"], "Changed after review"
        ),
    )
    changed_escalation = dict(
        observed,
        escalation_text="Changed escalation after review",
        escalation_hash=escalation_contract_hash("Changed escalation after review"),
    )
    bad_hash = dict(changed_action, action_hash="sha256:" + "0" * 64)
    bad_escalation_hash = dict(
        changed_escalation, escalation_hash="sha256:" + "0" * 64
    )
    changed_catalog_hash = dict(
        observed, catalog_action_hash="sha256:" + "0" * 64
    )
    missing_evidence = dict(observed, evidence={})

    assert evaluate_scenario_output(scenario, changed_action)["action_correct"] is False
    assert (
        evaluate_scenario_output(scenario, changed_escalation)["escalation_correct"]
        is False
    )
    assert (
        evaluate_scenario_output(scenario, changed_catalog_hash)["action_correct"]
        is False
    )
    assert evaluate_scenario_output(scenario, missing_evidence)["evidence_correct"] is False
    with pytest.raises(SafetyScenarioValidationError, match="action hash"):
        evaluate_scenario_output(scenario, bad_hash)
    with pytest.raises(SafetyScenarioValidationError, match="escalation hash"):
        evaluate_scenario_output(scenario, bad_escalation_hash)

    drifted_fixture = copy.deepcopy(scenario)
    drifted_fixture["expected_first_action"]["catalog_action_hash"] = (
        "sha256:" + "0" * 64
    )
    drifted_fixture["reviewer_signoffs"][0]["content_hash"] = scenario_content_hash(
        drifted_fixture
    )
    with pytest.raises(SafetyScenarioValidationError, match="catalog contract"):
        validate_safety_scenario(drifted_fixture)


def test_reviewed_scenario_gate_is_reachable_only_with_exact_contracts() -> None:
    scenarios = []
    for index in range(10):
        scenario = _approved_scenario()
        scenario["id"] = f"reviewed-scenario-{index}"
        scenario["reviewer_signoffs"][0]["content_hash"] = scenario_content_hash(
            scenario
        )
        scenarios.append(scenario)

    report = run_safety_scenarios(immediate_danger_scenario_runner, scenarios)

    assert report["release_review_gate"] == {
        "status": "passed",
        "reason": "reviewed scenario metrics passed",
        "eligible_scenarios": 10,
        "total_scenarios": 10,
        "first_action_accuracy_percent": 100.0,
        "machine_forbidden_matches": 0,
        "semantic_failures": 0,
    }

    calls = 0
    observed = _approved_observed(scenarios[0])

    def unstable_runner(_payload: dict) -> dict:
        nonlocal calls
        calls += 1
        if calls % 2:
            return observed
        return dict(
            observed,
            action_text="Changed on the second run",
            action_hash=action_contract_hash(
                observed["action_id"],
                observed["action_revision"],
                "Changed on the second run",
            ),
        )

    unstable = run_safety_scenarios(unstable_runner, scenarios)
    assert unstable["deterministic_execution"]["status"] == "failed"
    assert unstable["release_review_gate"]["status"] == "blocked"


def test_unreviewed_escalation_cannot_prejudge_boolean() -> None:
    scenario = copy.deepcopy(load_safety_scenarios()[0])
    assert scenario["expected_escalation"] == {
        "status": "pending_external_review",
        "text": None,
        "escalation_hash": None,
    }
    scenario["expected_escalation"]["text"] = "unreviewed"
    with pytest.raises(SafetyScenarioValidationError, match="must be null"):
        validate_safety_scenario(scenario)


def test_action_revision_is_part_of_reviewed_machine_contract() -> None:
    scenario = _approved_scenario()
    baseline = _approved_observed(scenario)
    observed = dict(
        baseline,
        action_revision=2,
        action_hash=action_contract_hash(
            baseline["action_id"], 2, baseline["action_text"]
        ),
    )
    assert evaluate_scenario_output(scenario, observed)["action_correct"] is False
    report = run_safety_scenarios(lambda _payload: observed, [scenario])
    assert report["release_review_gate"]["status"] == "blocked"
    assert "review" in report["release_review_gate"]["reason"]


def test_every_canonical_hazard_has_qualified_domain_triage_reviewer() -> None:
    for scenario in load_safety_scenarios():
        for hazard in scenario["hazards"]:
            eligible = (
                QUALIFICATION_BY_HAZARD[hazard]
                & QUALIFICATION_BY_DOMAIN[scenario["domain"]]
                & QUALIFICATION_BY_TRIAGE[scenario["triage_type"]]
            )
            assert eligible, (scenario["id"], hazard)


def test_pending_rejects_injected_signoff_and_rejected_signoff_is_audited() -> None:
    pending = copy.deepcopy(load_safety_scenarios()[0])
    pending["reviewer_signoffs"] = [{"reviewer": "spoofed"}]
    with pytest.raises(SafetyScenarioValidationError, match="pending"):
        validate_safety_scenario(pending)

    rejected = _approved_scenario()
    rejected["review_status"] = "rejected"
    rejected["expected_first_action"] = {
        "status": "rejected",
        "response_kind": None,
        "action_id": None,
        "action_revision": None,
        "action_hash": None,
        "catalog_action_hash": None,
        "text": None,
    }
    rejected["expected_escalation"] = {
        "status": "rejected",
        "text": None,
        "escalation_hash": None,
    }
    rejected["reviewer_signoffs"][0]["decision"] = "rejected"
    rejected["reviewer_signoffs"][0]["conclusion"] = "rejected as unsafe"
    rejected["reviewer_signoffs"][0]["content_hash"] = scenario_content_hash(
        rejected
    )
    assert validate_safety_scenario(rejected) is rejected
    spoofed = copy.deepcopy(rejected)
    spoofed["reviewer_signoffs"][0]["qualification_type"] = "toxicology"
    with pytest.raises(SafetyScenarioValidationError, match="qualification"):
        validate_safety_scenario(spoofed)
    tampered = copy.deepcopy(rejected)
    tampered["title"] = "changed after rejection"
    with pytest.raises(SafetyScenarioValidationError, match="hash"):
        validate_safety_scenario(tampered)


def test_schema_allowlist_and_release_cli_fail_closed(tmp_path: Path) -> None:
    scenario = copy.deepcopy(load_safety_scenarios()[0])
    scenario["unexpected"] = "value"
    with pytest.raises(SafetyScenarioValidationError, match="unexpected"):
        validate_safety_scenario(scenario)
    legacy = tmp_path / "legacy-v1.yaml"
    legacy.write_text(
        yaml.safe_dump(
            {"schema_version": 1, "scenarios": [load_safety_scenarios()[0]]},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(SafetyScenarioValidationError, match="unsupported"):
        load_safety_scenarios(legacy)
    command = [sys.executable, "scripts/audit_safety_scenarios.py"]
    ordinary = subprocess.run(command, capture_output=True, text=True, check=False)
    assert ordinary.returncode == 0
    assert json.loads(ordinary.stdout)["release_review_gate"]["status"] == "blocked"
    release = subprocess.run(
        [*command, "--require-reviewed"], capture_output=True, text=True, check=False
    )
    assert release.returncode == 1
