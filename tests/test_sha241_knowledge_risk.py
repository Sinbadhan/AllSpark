import copy
from pathlib import Path

import pytest

from allspark.core.database import Database
from allspark.core.i18n import get_language, set_language
from allspark.core.models import (
    KnowledgeEntry,
    KnowledgeValidationError,
    compute_content_hash,
    compute_risk_classification_hash,
    is_high_risk_knowledge,
    knowledge_transport_payload,
    normalize_knowledge_evidence,
    normalize_knowledge_risk_metadata,
    validate_knowledge_entry_schema,
)
from allspark.services.knowledge_engine import KnowledgeEngine, _risk_qualification_label
from allspark.services.knowledge_loader import load_knowledge
from allspark.services.knowledge_verifier import KnowledgeSigner
from allspark.services.safety_scenario_audit import audit_bundled_risk_metadata
from allspark.services.skf_manager import SKFPackage, _entry_checksum, import_skf
from allspark.services.spark_network import SparkNetwork


def _entry(**overrides) -> KnowledgeEntry:
    values = {
        "id": "safety/risk/test",
        "category": "engineering",
        "subcategory": "fire_structure",
        "priority": 1,
        "title": "Reviewed risk fixture",
        "summary": "A bounded fixture for risk classification.",
        "steps": ["Do the reviewed action"],
        "source": "pre_collapse",
        "risk_level": "high",
        "hazards": ["fire", "structural"],
        "review_status": "pending_external_review",
    }
    values.update(overrides)
    return KnowledgeEntry(**values)


def _risk_review(entry: KnowledgeEntry, hazard: str) -> dict:
    qualification = {
        "fire": "fire_safety",
        "structural": "structural_engineering",
    }[hazard]
    return {
        "signoff_version": 1,
        "reviewer_id": f"reviewer-{hazard}-001",
        "reviewer": f"Named {hazard} reviewer",
        "qualification_type": qualification,
        "qualification_evidence": f"registry:{qualification}:001",
        "covered_hazards": [hazard],
        "reviewed_at": "2026-07-16",
        "conclusion": "approved",
        "reservations": [],
        "classification_hash": compute_risk_classification_hash(entry),
    }


def _approved_entry() -> KnowledgeEntry:
    entry = _entry(
        applicable_when=["  intact reviewed fixture  "],
        review_status="approved",
    )
    normalize_knowledge_evidence(entry)
    entry.risk_reviews = [
        _risk_review(entry, "fire"),
        _risk_review(entry, "structural"),
    ]
    return entry


def _fully_reviewed_entry() -> KnowledgeEntry:
    entry = _approved_entry()
    entry.reviewer = "Named content reviewer"
    entry.qualification = "Emergency physician"
    entry.review_date = "2026-07-16"
    entry.citation = "Local safety manual, section 4"
    entry.signoff_version = 1
    entry.content_hash = compute_content_hash(entry)
    return entry


def test_all_bundled_entries_have_explicit_fail_closed_risk_metadata() -> None:
    entries = load_knowledge()
    assert len(entries) == 152
    assert all(entry.risk_level == "pending_review" for entry in entries)
    assert all(entry.hazards == ["unknown"] for entry in entries)
    assert all(entry.review_status == "pending_external_review" for entry in entries)
    assert all(is_high_risk_knowledge(entry) for entry in entries)
    assert audit_bundled_risk_metadata() == {
        "total": 152,
        "metadata_present": 152,
        "metadata_missing": 0,
        "substantively_classified": 0,
        "unknown_hazard_count": 152,
        "unknown_hazard_ids": [entry.id for entry in entries],
        "pending_review_count": 152,
        "approved_count": 0,
        "fail_safe_high_risk_count": 152,
    }


def test_wholly_legacy_risk_state_normalizes_but_partial_state_is_rejected(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "risk.db")
    legacy = _entry(risk_level="", hazards=[], review_status="")
    db.save_knowledge(legacy)
    saved = db.get_knowledge(legacy.id)
    assert saved is not None
    assert (saved.risk_level, saved.hazards, saved.review_status) == (
        "pending_review",
        ["unknown"],
        "pending_external_review",
    )
    partial = _entry(id="partial", hazards=[])
    with pytest.raises(KnowledgeValidationError, match="hazards"):
        db.save_knowledge(partial)
    assert db.get_knowledge("partial") is None
    db.close()


def test_approved_multi_reviewer_hash_survives_normalization_and_db_roundtrip(
    tmp_path: Path,
) -> None:
    entry = _approved_entry()
    validate_knowledge_entry_schema(entry)
    db = Database(tmp_path / "approved.db")
    db.save_knowledge(entry)
    saved = db.get_knowledge(entry.id)
    assert saved is not None
    assert saved.applicable_when == ["intact reviewed fixture"]
    assert saved.review_status == "approved"
    assert len(saved.risk_reviews) == 2
    assert all(
        review["classification_hash"] == compute_risk_classification_hash(saved)
        for review in saved.risk_reviews
    )
    validate_knowledge_entry_schema(saved)
    db.close()


def test_approved_spoof_duplicate_hazard_and_tamper_fail_closed() -> None:
    spoof = _entry(review_status="approved")
    with pytest.raises(KnowledgeValidationError, match="incomplete"):
        validate_knowledge_entry_schema(spoof)
    duplicate = _entry(hazards=["fire", "fire"])
    with pytest.raises(KnowledgeValidationError, match="hazards"):
        validate_knowledge_entry_schema(duplicate)
    approved = _approved_entry()
    tampered = copy.deepcopy(approved)
    tampered.summary = "changed after risk review"
    with pytest.raises(KnowledgeValidationError, match="hash"):
        validate_knowledge_entry_schema(tampered)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("risk_level", "critical"),
        ("hazards", ["fire"]),
        ("review_status", "rejected"),
    ],
)
def test_risk_metadata_tamper_changes_hash_checksum_and_signature(
    field: str, value,
) -> None:
    original = _approved_entry()
    tampered = copy.deepcopy(original)
    setattr(tampered, field, value)
    signer = KnowledgeSigner(secret_key="sha241")
    assert compute_content_hash(original) != compute_content_hash(tampered) or field == "review_status"
    assert _entry_checksum(original) != _entry_checksum(tampered)
    assert not signer.verify_entry(tampered, signer.sign_entry(original))


def test_risk_review_tamper_invalidates_checksum_signature_and_local_review() -> None:
    original = _approved_entry()
    tampered = copy.deepcopy(original)
    tampered.risk_reviews[0]["reviewer"] = "Spoofed Reviewer"
    signer = KnowledgeSigner(secret_key="sha241")
    assert _entry_checksum(original) != _entry_checksum(tampered)
    assert not signer.verify_entry(tampered, signer.sign_entry(original))
    tampered.risk_reviews[0]["classification_hash"] = "sha256:" + "0" * 64
    with pytest.raises(KnowledgeValidationError, match="hash"):
        validate_knowledge_entry_schema(tampered)


def test_rejected_classification_keeps_named_local_decision() -> None:
    entry = _entry(
        hazards=["fire"],
        review_status="rejected",
    )
    review = _risk_review(entry, "fire")
    review["conclusion"] = "rejected"
    entry.risk_reviews = [review]
    validate_knowledge_entry_schema(entry)
    assert is_high_risk_knowledge(entry) is True


def test_skf_approved_claim_is_preserved_but_local_trust_is_downgraded(
    tmp_path: Path,
) -> None:
    entry = _approved_entry()
    package = SKFPackage()
    package.spark_id = "spark-sha241"
    package.knowledge_entries = [entry]
    path = package.export_to_file(str(tmp_path / "risk.skf"))
    db = Database(tmp_path / "receiver.db")
    result = import_skf(db, path, verify=True, skip_duplicates=False)
    assert result["imported"]["knowledge"] == 1
    saved = db.get_knowledge(entry.id)
    assert saved is not None
    assert saved.review_status == "pending_external_review"
    assert saved.risk_reviews == []
    assert len(saved.risk_review_claims) == 2
    assert is_high_risk_knowledge(saved) is True
    db.close()


def test_network_risk_roundtrip_is_signed_and_downgraded(tmp_path: Path) -> None:
    entry = _approved_entry()
    receiver_db = Database(tmp_path / "network.db")
    network = SparkNetwork(db=receiver_db)
    result = network.receive_knowledge([knowledge_transport_payload(entry)])
    assert result["pending_count"] == 1
    saved = receiver_db.get_knowledge(entry.id)
    assert saved is not None
    assert saved.review_status == "pending_external_review"
    assert saved.risk_reviews == []
    assert len(saved.risk_review_claims) == 2
    receiver_db.close()


def test_api_payload_exposes_fail_closed_classification_and_review_counts() -> None:
    entry = _approved_entry()
    payload = KnowledgeEngine.entry_payload(entry)
    assert payload["risk_level"] == "high"
    assert payload["hazards"] == ["fire", "structural"]
    assert payload["risk_review_status"] == "approved"
    assert payload["risk_review_counts"] == {"local": 2, "external_claims": 0}
    assert len(payload["risk_reviews"]) == 2
    assert payload["risk_review_claims"] == []
    assert payload["actionable_content"] is False
    assert payload["content_access"] == "withheld_pending_review"
    assert payload["steps"] == []


def test_actionable_content_requires_both_content_and_risk_review() -> None:
    content_only = _entry(
        reviewer="Named content reviewer",
        qualification="Emergency physician",
        review_date="2026-07-16",
        citation="Local safety manual, section 4",
        signoff_version=1,
    )
    content_only.content_hash = compute_content_hash(content_only)
    assert KnowledgeEngine.entry_payload(content_only)["actionable_content"] is False

    fully_reviewed = _fully_reviewed_entry()
    payload = KnowledgeEngine.entry_payload(fully_reviewed)
    assert payload["actionable_content"] is True
    assert payload["content_access"] == "available"
    assert payload["summary"] == fully_reviewed.summary
    assert payload["steps"] == ["Do the reviewed action"]


@pytest.mark.parametrize(
    "entry_id, forbidden",
    [
        ("survival/fire/methods/battery/en", "Touch both battery terminals"),
        ("survival/food/plants/universal_test/en", "induce vomiting"),
        ("medicine/surgery/basic", "脓肿切开"),
    ],
)
def test_bundled_pending_review_actions_never_leave_output_contract(
    entry_id: str, forbidden: str,
) -> None:
    entry = next(value for value in load_knowledge() if value.id == entry_id)
    payload = KnowledgeEngine.entry_payload(entry)
    output = KnowledgeEngine(type("DB", (), {})()).format_entry(entry)
    assert payload["actionable_content"] is False
    assert payload["steps"] == []
    assert payload["prerequisites"] == []
    assert payload["warnings"] == []
    assert forbidden not in payload["summary"]
    assert forbidden not in output


def test_normalize_all_empty_is_idempotent() -> None:
    entry = KnowledgeEntry(
        id="legacy",
        category="survival",
        subcategory="water",
        priority=1,
        title="Legacy",
        summary="Legacy risk metadata is absent.",
    )
    normalize_knowledge_risk_metadata(entry)
    normalize_knowledge_risk_metadata(entry)
    assert entry.risk_level == "pending_review"
    assert entry.hazards == ["unknown"]
    assert entry.review_status == "pending_external_review"


@pytest.mark.parametrize(
    (
        "language",
        "status_text",
        "hazard_text",
        "classification_text",
        "qualification_text",
    ),
    [
        (
            "zh",
            "风险分类已完成外部复核",
            "火灾危害",
            "风险分类",
            "消防安全专业人员",
        ),
        (
            "en",
            "Risk classification externally reviewed",
            "Fire hazard",
            "Risk classification",
            "Fire safety specialist",
        ),
    ],
)
def test_api_cli_and_dom_show_risk_context_before_actions(
    language: str,
    status_text: str,
    hazard_text: str,
    classification_text: str,
    qualification_text: str,
    tmp_path: Path,
) -> None:
    previous = get_language()
    try:
        set_language(language, persist=False)
        entry = _fully_reviewed_entry()
        payload = KnowledgeEngine.entry_payload(entry)
        assert payload["risk_review_status_label"] == status_text
        assert hazard_text in payload["hazard_labels"]
        assert payload["risk_reviews"][0]["qualification_label"] == qualification_text
        db = Database(tmp_path / f"cli-{language}.db")
        output = KnowledgeEngine(db).format_entry(entry)
        db.close()
        assert output.index(classification_text) < output.index("1. Do the reviewed action")
        assert hazard_text in output
        assert qualification_text in output
        assert "External risk-review claim" not in output
        repo = Path("allspark/templates/repository.html").read_text(encoding="utf-8")
        index = Path("allspark/templates/index.html").read_text(encoding="utf-8")
        assert repo.index("REPO_I18N.risk_classification") < repo.index("${steps ?")
        assert index.index("knowledge_risk_classification_label") < index.index(
            "entry.steps && entry.steps.length"
        )
    finally:
        set_language(previous, persist=False)


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("zh", "无法识别的资质（future specialist）"),
        ("en", "Unrecognized qualification (future specialist)"),
    ],
)
def test_unknown_qualification_has_readable_localized_fallback(
    language: str, expected: str
) -> None:
    previous = get_language()
    try:
        set_language(language, persist=False)
        assert _risk_qualification_label("future_specialist") == expected
    finally:
        set_language(previous, persist=False)
