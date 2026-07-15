import copy
from pathlib import Path

import pytest

from allspark.core.database import Database
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
from allspark.services.knowledge_engine import KnowledgeEngine
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
