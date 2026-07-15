import copy
import hashlib
import hmac
import json
import socket
import sqlite3
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from allspark.core.database import Database
from allspark.core.i18n import get_language, set_language
from allspark.core.models import (
    KNOWLEDGE_TRANSPORT_FIELDS,
    KnowledgeEntry,
    KnowledgeEvidenceValidationError,
    compute_content_hash,
    derive_verification_level,
    knowledge_transport_payload,
    normalize_knowledge_evidence,
)
from allspark.services.knowledge_audit import audit_bundled_knowledge
from allspark.services.knowledge_engine import KnowledgeEngine
from allspark.services.knowledge_loader import load_knowledge
from allspark.services.knowledge_verifier import KnowledgeSigner, KnowledgeVerifier
from allspark.services.skf_manager import (
    SKFArchiveValidationError,
    SKFPackage,
    import_skf,
)
from allspark.services.spark_network import ChannelType, NodeStatus, SparkNetwork, SparkNode


def _entry(**overrides) -> KnowledgeEntry:
    values = {
        "id": "medical/test/bleeding",
        "category": "medical",
        "subcategory": "first_aid",
        "priority": 0,
        "title": "Test entry",
        "summary": "Test summary",
        "steps": ["Act"],
        "source": "pre_collapse",
    }
    values.update(overrides)
    return KnowledgeEntry(**values)


def _reference(source_id: str, **overrides) -> dict:
    value = {
        "source_id": source_id,
        "title": f"Source {source_id}",
        "locator": "Chapter 2, section 4",
        "url": "https://example.invalid/reference",
        "local_status": "verified",
        "verified_by": "local-reviewer",
        "verified_at": "2026-07-15",
    }
    value.update(overrides)
    return value


def _field_record(**overrides) -> dict:
    value = {
        "record_id": "field-001",
        "source_id": "team-alpha",
        "conditions": ["dry weather", "adult subject"],
        "outcome": "Succeeded without injury",
        "recorded_at": "2026-07-14",
        "locator": "local-log:field-001",
        "local_status": "verified",
        "verified_by": "local-reviewer",
        "verified_at": "2026-07-15",
    }
    value.update(overrides)
    return value


def test_verification_is_derived_only_from_local_auditable_evidence() -> None:
    assert derive_verification_level(_entry(verification="field_tested")) == "unverified"
    assert derive_verification_level(_entry(verification="expert_verified")) == "unverified"
    assert derive_verification_level(
        _entry(references=[_reference("same"), _reference("same")])
    ) == "unverified"
    assert derive_verification_level(
        _entry(references=[_reference("a"), _reference("b", locator="")])
    ) == "unverified"
    assert derive_verification_level(
        _entry(references=[_reference("a"), _reference("b")])
    ) == "cross_ref"
    assert derive_verification_level(_entry(field_records=[_field_record()])) == "field_tested"
    assert derive_verification_level(
        _entry(references=[_reference(" WHO "), _reference("who")])
    ) == "unverified"


def test_dates_and_expert_signoff_are_structurally_validated() -> None:
    invalid_reference = _reference("a", verified_at="not-a-date")
    invalid_record = _field_record(recorded_at="yesterday")
    assert derive_verification_level(
        _entry(references=[invalid_reference, _reference("b")])
    ) == "unverified"
    assert derive_verification_level(_entry(field_records=[invalid_record])) == "unverified"
    signed = _entry(
        reviewer="Dr A", qualification="Emergency physician",
        review_date="not-a-date", citation="Manual section 2", signoff_version=1,
    )
    signed.content_hash = compute_content_hash(signed)
    assert signed.is_signed_off() is False


def test_untrusted_evidence_is_rejected_without_stripping_safety_boundary(
    tmp_path: Path,
) -> None:
    entry = _entry(
        references=[_reference(f"source-{i}", title="x" * 5000) for i in range(100)],
        field_records=[_field_record(record_id=f"record-{i}") for i in range(100)],
        applicable_when=["  ", " condition "],
        contraindications=[42, " boundary "],
    )
    with pytest.raises(KnowledgeEvidenceValidationError):
        normalize_knowledge_evidence(entry)
    assert entry.steps == ["Act"]
    assert entry.contraindications == [42, " boundary "]
    db = Database(tmp_path / "reject.db")
    with pytest.raises(KnowledgeEvidenceValidationError):
        db.save_knowledge(entry)
    assert db.get_knowledge(entry.id) is None
    db.close()


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("references", [_reference("changed")]),
        ("field_records", [_field_record(outcome="changed")]),
        ("applicable_when", ["changed condition"]),
        ("contraindications", ["changed contraindication"]),
    ],
)
def test_evidence_and_boundaries_invalidate_hash_and_signature(field: str, changed) -> None:
    original = _entry(
        references=[_reference("a")],
        field_records=[_field_record()],
        applicable_when=["visible life-threatening bleeding"],
        contraindications=["do not delay emergency services"],
    )
    tampered = _entry(
        references=[_reference("a")],
        field_records=[_field_record()],
        applicable_when=["visible life-threatening bleeding"],
        contraindications=["do not delay emergency services"],
    )
    setattr(tampered, field, changed)
    signer = KnowledgeSigner(secret_key="sha240")
    signature = signer.sign_entry(original)
    assert compute_content_hash(original) != compute_content_hash(tampered)
    assert not signer.verify_entry(tampered, signature)


@pytest.mark.parametrize("field", ["verification_claim", "source_claim"])
def test_audit_claim_tampering_invalidates_transport_integrity(field: str) -> None:
    from allspark.services.skf_manager import _entry_checksum

    original = _entry(verification_claim="field_tested", source_claim="pre_collapse")
    tampered = _entry(verification_claim="field_tested", source_claim="pre_collapse")
    setattr(tampered, field, "tampered")
    signer = KnowledgeSigner(secret_key="sha240")
    assert not signer.verify_entry(tampered, signer.sign_entry(original))
    assert _entry_checksum(original) != _entry_checksum(tampered)


@pytest.mark.parametrize(
    "field",
    [
        "reviewer", "qualification", "review_date", "citation", "content_hash",
        "signoff_version",
    ],
)
def test_external_review_claim_tampering_invalidates_all_integrity_pins(field: str) -> None:
    from allspark.services.skf_manager import _entry_checksum

    claim = {
        "reviewer": "Remote Expert", "qualification": "Claimed credential",
        "review_date": "2026-07-15", "citation": "Manual section 2",
        "content_hash": "sha256:" + "c" * 64, "signoff_version": 1,
        "local_status": "external_claim",
    }
    original = _entry(review_claim=copy.deepcopy(claim))
    tampered = _entry(review_claim=copy.deepcopy(claim))
    tampered.review_claim[field] = (
        2 if field == "signoff_version" else str(tampered.review_claim[field]) + " changed"
    )
    signer = KnowledgeSigner(secret_key="sha240")
    assert compute_content_hash(original) != compute_content_hash(tampered)
    assert _entry_checksum(original) != _entry_checksum(tampered)
    assert not signer.verify_entry(tampered, signer.sign_entry(original))


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("subcategory", "changed"),
        ("prerequisites", ["changed prerequisite"]),
        ("verification", "cross_ref"),
        ("version", 2),
        ("language", "en"),
    ],
)
def test_signature_covers_every_spark_semantic_field(field: str, changed) -> None:
    original = _entry(prerequisites=["required equipment"], verification="unverified")
    tampered = copy.deepcopy(original)
    setattr(tampered, field, changed)
    signer = KnowledgeSigner(secret_key="sha240")
    assert set(knowledge_transport_payload(original)) == set(KNOWLEDGE_TRANSPORT_FIELDS)
    assert not signer.verify_entry(tampered, signer.sign_entry(original))


def test_unsafe_legacy_delimiter_signature_has_no_implicit_fallback() -> None:
    entry = _entry()
    old_payload = "|".join([
        entry.id, entry.title, entry.summary, entry.category, str(entry.priority),
        entry.source, json.dumps(entry.steps), json.dumps(entry.warnings),
    ])
    legacy_signature = hmac.new(
        b"sha240", old_payload.encode(), hashlib.sha256
    ).hexdigest()
    assert not KnowledgeSigner(secret_key="sha240").verify_entry(entry, legacy_signature)


def test_database_migrates_legacy_claims_and_persists_evidence(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE knowledge (
        id TEXT PRIMARY KEY, category TEXT, subcategory TEXT, priority INTEGER,
        title TEXT, summary TEXT, steps TEXT, prerequisites TEXT, warnings TEXT,
        verification TEXT, source TEXT, version INTEGER, language TEXT,
        reviewer TEXT, qualification TEXT, review_date TEXT, citation TEXT,
        content_hash TEXT, signoff_version INTEGER)"""
    )
    conn.execute(
        "INSERT INTO knowledge VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("legacy", "medical", "first_aid", 0, "Legacy", "Claim", "[]", "[]", "[]",
         "experience_based", "self_learned", 1, "en", "", "", "", "", "", 0),
    )
    conn.commit()
    conn.close()

    db = Database(path)
    migrated = db.get_knowledge("legacy")
    assert migrated is not None
    assert migrated.verification == "unverified"
    assert migrated.verification_claim == "experience_based"
    assert migrated.risk_level == "pending_review"
    assert migrated.hazards == ["unknown"]
    assert migrated.review_status == "pending_external_review"
    migrated.references = [_reference("a"), _reference("b")]
    migrated.applicable_when = ["only when tested"]
    db.save_knowledge(migrated)
    reloaded = db.get_knowledge("legacy")
    assert reloaded is not None
    assert reloaded.references == migrated.references
    assert reloaded.applicable_when == ["only when tested"]
    db.close()


def test_bundled_claims_remain_unverified_and_local_evidence_survives_reload(
    tmp_path: Path,
) -> None:
    entries = load_knowledge()
    assert entries
    assert all(entry.verification == "unverified" for entry in entries)
    db = Database(tmp_path / "reload.db")
    for _ in range(2):
        for entry in load_knowledge():
            db.save_bundled_knowledge(entry)
    assert all(entry.verification == "unverified" for entry in db.get_knowledge_by_priority(3))

    target = load_knowledge()[0]
    db.save_bundled_knowledge(target)
    locally_verified = db.get_knowledge(target.id)
    assert locally_verified is not None
    locally_verified.references = [_reference("a"), _reference("b")]
    db.save_knowledge(locally_verified)
    assert db.get_knowledge(target.id).verification == "cross_ref"
    for _ in range(2):
        fresh = next(entry for entry in load_knowledge() if entry.id == target.id)
        db.save_bundled_knowledge(fresh)
    assert db.get_knowledge(target.id).verification == "cross_ref"
    assert len(db.get_knowledge(target.id).references) == 2

    changed = next(entry for entry in load_knowledge() if entry.id == target.id)
    changed.title += " changed"
    changed.version += 1
    db.save_bundled_knowledge(changed)
    invalidated = db.get_knowledge(target.id)
    assert invalidated is not None
    assert invalidated.verification == "unverified"
    assert invalidated.references == []
    db.close()


def test_verifier_rejects_imported_independence_claims() -> None:
    entry = _entry(references=[
        _reference("forged", local_status="external_claim"),
        _reference("forged-2", local_status="external_claim"),
    ])
    report = KnowledgeVerifier().verify_entry(entry)
    cross_ref = next(result for result in report.results if result.step == "cross_reference")
    assert cross_ref.passed is False
    assert cross_ref.details["supporting_count"] == 0
    assert report.level == "unverified"


def test_skf_import_preserves_claims_but_externalizes_evidence(tmp_path: Path) -> None:
    pkg = SKFPackage()
    pkg.spark_id = "attacker"
    pkg.knowledge_entries = [_entry(
        source="pre_collapse",
        verification="expert_verified",
        references=[_reference("a"), _reference("b")],
        field_records=[_field_record()],
        applicable_when=["claimed condition"],
        contraindications=["claimed boundary"],
        review_claim={
            "reviewer": "Remote Expert",
            "qualification": "Claimed credential",
            "review_date": "2026-07-15",
            "citation": "Remote manual section 4",
            "content_hash": "sha256:" + "b" * 64,
            "signoff_version": 2,
            "local_status": "local_verified",
        },
    )]
    path = pkg.export_to_file(str(tmp_path / "attack.skf"))
    db = Database(tmp_path / "target.db")
    assert import_skf(db, path)["status"] == "ok"
    saved = db.get_knowledge("medical/test/bleeding")
    assert saved is not None
    assert saved.source == "other_spark"
    assert saved.source_claim == "pre_collapse"
    assert saved.verification == "unverified"
    assert saved.verification_claim == "expert_verified"
    assert saved.review_claim["reviewer"] == "Remote Expert"
    assert saved.review_claim["local_status"] == "external_claim"
    assert saved.reviewer == ""
    assert all(ref["local_status"] == "external_claim" for ref in saved.references)
    assert all(record["local_status"] == "external_claim" for record in saved.field_records)
    assert all("verified_by" not in ref and "verified_at" not in ref for ref in saved.references)
    assert all(
        "verified_by" not in record and "verified_at" not in record
        for record in saved.field_records
    )
    assert saved.applicable_when == ["claimed condition"]
    assert saved.contraindications == ["claimed boundary"]
    db.close()


@pytest.mark.parametrize("tamper_field", ["locator", "verification_claim"])
def test_real_skf_zip_evidence_or_claim_tamper_is_rejected(
    tmp_path: Path, tamper_field: str
) -> None:
    pkg = SKFPackage()
    pkg.spark_id = "source"
    pkg.knowledge_entries = [_entry(
        references=[_reference("a")],
        verification_claim="field_tested",
        source_claim="pre_collapse",
    )]
    original = Path(pkg.export_to_file(str(tmp_path / "original.skf")))
    valid = SKFPackage.import_from_file(str(original))
    assert valid.validate() == []
    assert valid.knowledge_entries[0].verification_claim == "field_tested"
    with ZipFile(original) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    knowledge = json.loads(files["knowledge.json"])
    if tamper_field == "locator":
        knowledge[0]["references"][0]["locator"] = "tampered locator"
    else:
        knowledge[0]["verification_claim"] = "expert_verified"
    files["knowledge.json"] = json.dumps(knowledge).encode()
    tampered = tmp_path / "tampered.skf"
    with ZipFile(tampered, "w", ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    errors = SKFPackage.import_from_file(str(tampered)).validate()
    assert any("checksum mismatch" in error for error in errors)


def test_spark_network_round_trip_preserves_claims_not_local_trust(tmp_path: Path) -> None:
    sender_db = Database(tmp_path / "sender.db")
    receiver_db = Database(tmp_path / "receiver.db")
    for db in (sender_db, receiver_db):
        db.save_survivor_state("network_shared_secret", "sha240-secret")
    entry = _entry(
        references=[_reference("a"), _reference("b")],
        field_records=[_field_record()],
        applicable_when=["condition"], contraindications=["boundary"],
        verification_claim="expert_verified", source_claim="pre_collapse",
        reviewer="Dr A", qualification="Emergency physician",
        review_date="2026-07-15", citation="Manual section 2", signoff_version=1,
    )
    entry.content_hash = compute_content_hash(entry)
    sender_db.save_knowledge(entry)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    receiver = SparkNetwork(db=receiver_db, spark_id="receiver")
    sender = SparkNetwork(db=sender_db, spark_id="sender")
    assert receiver.start_exchange_server(host="127.0.0.1", port=port)["status"] == "started"
    try:
        sender.nodes["receiver"] = SparkNode(
            node_id="receiver", spark_id="receiver", address="127.0.0.1", port=port,
            channel=ChannelType.LAN, status=NodeStatus.CONNECTED,
        )
        result = sender.send_knowledge("receiver", [entry.id])
        assert result["status"] == "ok"
        saved = receiver_db.get_knowledge(entry.id)
        assert saved is not None
        assert saved.verification == "unverified"
        assert saved.verification_claim == "expert_verified"
        assert saved.source == "other_spark"
        assert saved.source_claim == "pre_collapse"
        assert saved.review_claim["reviewer"] == "Dr A"
        assert saved.review_claim["qualification"] == "Emergency physician"
        assert saved.review_claim["local_status"] == "external_claim"
        assert saved.applicable_when == ["condition"]
        assert saved.contraindications == ["boundary"]
        assert all(ref["local_status"] == "external_claim" for ref in saved.references)
        assert all("verified_by" not in ref for ref in saved.references)
        assert saved.reviewer == ""
        assert saved.content_hash == ""
        assert saved.signoff_version == 0
    finally:
        receiver.stop_discovery()
        sender_db.close()
        receiver_db.close()


@pytest.mark.parametrize(
    "payload",
    [
        "not-an-object",
        {"title": "T", "summary": "S"},
        {"id": "bad/empty-title", "title": "", "summary": "S"},
        {"id": "bad/empty-summary", "title": "T", "summary": ""},
        {"id": "bad/oversized", "title": "x" * 1025, "summary": "S"},
        {"id": "bad/steps", "title": "T", "summary": "S", "steps": "not-a-list"},
        {"id": "bad/verification", "title": "T", "summary": "S", "verification": "made_up"},
        {"id": "bad/language", "title": "T", "summary": "S", "language": "fr"},
    ],
)
def test_unsigned_network_malformed_entries_are_rejected_without_write(
    tmp_path: Path, payload
) -> None:
    db = Database(tmp_path / "malformed.db")
    result = SparkNetwork(db=db).receive_knowledge([payload])
    assert result["accepted_count"] == 0
    assert result["pending_count"] == 0
    assert result["rejected_count"] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0] == 0
    db.close()


def test_network_rejects_non_list_batch_without_crashing(tmp_path: Path) -> None:
    db = Database(tmp_path / "bad-batch.db")
    result = SparkNetwork(db=db).receive_knowledge({"id": "not-a-list"})
    assert result["status"] == "error"
    assert db.conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0] == 0
    db.close()


def test_legacy_skf_checksum_remains_compatible(tmp_path: Path) -> None:
    item = {
        "id": "legacy-skf", "category": "survival", "subcategory": "water",
        "priority": 1, "title": "Legacy", "content": {
            "summary": "Summary", "steps": [], "prerequisites": [], "warnings": []},
        "verification": "field_tested", "source": "pre_collapse", "version": 1,
        "language": "en",
    }
    legacy_payload = {
        "id": "legacy-skf", "category": "survival", "subcategory": "water",
        "priority": 1, "title": "Legacy", "summary": "Summary", "steps": [],
        "prerequisites": [], "warnings": [], "verification": "field_tested",
        "source": "pre_collapse", "version": 1, "language": "en",
    }
    legacy_canonical = json.dumps(legacy_payload, sort_keys=True, ensure_ascii=False)
    item["checksum"] = "sha256:" + hashlib.sha256(legacy_canonical.encode()).hexdigest()
    path = tmp_path / "legacy.skf"
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps({"skf": {"version": "1.0", "spark_id": "old"}}))
        archive.writestr("knowledge.json", json.dumps([item]))
        archive.writestr("experience.json", "[]")
    assert SKFPackage.import_from_file(str(path)).validate() == []


def _write_attack_skf(path: Path, knowledge, *, duplicate_manifest: bool = False) -> Path:
    manifest = json.dumps({"skf": {"version": "1.0", "spark_id": "attack"}})
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", manifest)
        if duplicate_manifest:
            archive.writestr("manifest.json", manifest)
        archive.writestr("knowledge.json", json.dumps(knowledge))
        archive.writestr("experience.json", "[]")
    return path


def _minimal_skf_item(entry_id: str = "stable-id") -> dict:
    return {
        "id": entry_id, "category": "survival", "subcategory": "water",
        "priority": 1, "title": "Title", "content": {
            "summary": "Summary", "steps": [], "prerequisites": [], "warnings": []},
        "verification": "unverified", "source": "other_spark", "version": 1,
        "language": "en",
    }


def test_skf_structural_errors_cannot_be_bypassed_with_verify_false(tmp_path: Path) -> None:
    item = _minimal_skf_item()
    item["references"] = [{}]
    path = _write_attack_skf(tmp_path / "invalid-evidence.skf", [item])
    db = Database(tmp_path / "no-partial.db")
    result = import_skf(db, str(path), verify=False)
    assert result["status"] == "validation_error"
    assert db.get_knowledge("stable-id") is None
    assert db.conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0] == 0
    db.close()


@pytest.mark.parametrize("entry_id", ["", None, "<>\"'&"])
def test_skf_requires_stable_nonempty_id(tmp_path: Path, entry_id) -> None:
    item = _minimal_skf_item()
    item["id"] = entry_id
    path = _write_attack_skf(tmp_path / f"missing-{entry_id!s}.skf", [item])
    with pytest.raises(SKFArchiveValidationError):
        SKFPackage.import_from_file(str(path))


def test_skf_rejects_duplicate_members_and_compression_bomb(tmp_path: Path) -> None:
    duplicate = _write_attack_skf(
        tmp_path / "duplicate.skf", [_minimal_skf_item()], duplicate_manifest=True
    )
    with pytest.raises(SKFArchiveValidationError, match="Duplicate"):
        SKFPackage.import_from_file(str(duplicate))

    bomb = tmp_path / "bomb.skf"
    with ZipFile(bomb, "w", ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps({"skf": {"spark_id": "bomb"}}))
        archive.writestr("knowledge.json", "A" * 1_000_000)
    with pytest.raises(SKFArchiveValidationError, match="compression ratio"):
        SKFPackage.import_from_file(str(bomb))


def test_skf_rejects_unexpected_member_and_missing_manifest(tmp_path: Path) -> None:
    unexpected = tmp_path / "unexpected-member.skf"
    with ZipFile(unexpected, "w", ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps({"skf": {"version": "1.0"}}))
        archive.writestr("unexpected.bin", "not allowed")
    with pytest.raises(SKFArchiveValidationError, match="Unexpected SKF members"):
        SKFPackage.import_from_file(str(unexpected))

    missing_manifest = tmp_path / "missing-manifest.skf"
    with ZipFile(missing_manifest, "w", ZIP_DEFLATED) as archive:
        archive.writestr("knowledge.json", "[]")
    with pytest.raises(SKFArchiveValidationError, match="Missing manifest"):
        SKFPackage.import_from_file(str(missing_manifest))


def test_skf_rejects_entry_count_content_and_archive_size_limits(
    tmp_path: Path, monkeypatch
) -> None:
    too_many = [_minimal_skf_item(f"entry-{index}") for index in range(2049)]
    with pytest.raises(SKFArchiveValidationError, match="entry count"):
        SKFPackage.import_from_file(
            str(_write_attack_skf(tmp_path / "too-many.skf", too_many))
        )

    too_many_steps = _minimal_skf_item("steps")
    too_many_steps["content"]["steps"] = ["step"] * 129
    with pytest.raises(SKFArchiveValidationError, match="steps count"):
        SKFPackage.import_from_file(
            str(_write_attack_skf(tmp_path / "steps.skf", [too_many_steps]))
        )

    oversized = _minimal_skf_item("oversized")
    oversized["content"]["summary"] = "x" * 16_385
    with pytest.raises(SKFArchiveValidationError, match="summary"):
        SKFPackage.import_from_file(
            str(_write_attack_skf(tmp_path / "oversized.skf", [oversized]))
        )

    valid = _write_attack_skf(tmp_path / "compressed-size.skf", [_minimal_skf_item()])
    import allspark.services.skf_manager as skf_module
    monkeypatch.setattr(skf_module, "_SKF_ARCHIVE_COMPRESSED_MAX", valid.stat().st_size - 1)
    with pytest.raises(SKFArchiveValidationError, match="compressed size"):
        SKFPackage.import_from_file(str(valid))


def test_summary_payload_is_bounded_and_detail_preserves_evidence() -> None:
    entry = _entry(
        references=[_reference("a")],
        field_records=[_field_record()],
        applicable_when=["condition"],
        contraindications=["boundary"],
    )
    summary = KnowledgeEngine.entry_payload(entry, detail=False)
    detail = KnowledgeEngine.entry_payload(entry, detail=True)
    assert "references" not in summary
    assert "field_records" not in summary
    assert "applicable_when" not in summary
    assert summary["evidence_counts"] == {
        "verified_references": 1,
        "verified_field_records": 1,
        "external_reference_claims": 0,
        "external_field_claims": 0,
        "local_expert_reviews": 0,
        "external_review_claims": 0,
    }
    assert detail["references"][0]["trust_status"] == "local_verified"
    assert detail["field_records"][0]["trust_status"] == "local_verified"
    assert len(json.dumps(summary, ensure_ascii=False)) < 5000

    signed = _entry(
        reviewer="Dr Local", qualification="Emergency physician",
        review_date="2026-07-15", citation="Local manual section 5",
        signoff_version=1,
    )
    signed.content_hash = compute_content_hash(signed)
    signed_detail = KnowledgeEngine.entry_payload(signed)
    assert signed_detail["verification"] == "expert_verified"
    assert signed_detail["local_review"]["reviewer"] == "Dr Local"
    assert signed_detail["external_review_claim"] == {}


def test_bundled_high_risk_audit_is_explicit_and_fail_closed() -> None:
    result = audit_bundled_knowledge()
    assert result["total"] == 152
    assert result["high_risk"] == 152
    assert result["classification_mode"] == "explicit_metadata_fail_closed"
    assert "SHA-241" in result["classification_limit"]
    assert result["verified_high_risk"] + result["unverified_high_risk"] == result["high_risk"]
    assert result["violations"] == []
    assert result["legacy_level_entries"] == []
    medicine = [entry for entry in load_knowledge() if entry.category == "medicine"]
    assert len(medicine) == 10
    from allspark.core.models import is_high_risk_knowledge
    assert all(is_high_risk_knowledge(entry) for entry in medicine)
    for category in ("chemistry", "energy", "engineering", "defense", "mechanical"):
        entries = [entry for entry in load_knowledge() if entry.category == category]
        assert entries, category
        assert all(is_high_risk_knowledge(entry) for entry in entries), category


@pytest.mark.parametrize("language", ["zh", "en"])
def test_qa_and_dom_put_high_risk_boundaries_before_steps(language: str) -> None:
    previous = get_language()
    try:
        set_language(language, persist=False)
        entry = _entry(
            references=[_reference("a")], applicable_when=["condition"],
            field_records=[_field_record(
                local_status="external_claim", verified_by="", verified_at=""
            )],
            review_claim={
                "reviewer": "External Reviewer",
                "qualification": "Emergency physician",
                "review_date": "2026-07-15",
                "citation": "Manual section 2",
                "content_hash": "a" * 64,
                "signoff_version": 1,
                "local_status": "external_claim",
            },
            contraindications=["boundary"], steps=["action"],
        )
        rendered = KnowledgeEngine.entry_payload(entry)
        assert rendered["risk_notice"]
        db = type("DB", (), {})()
        text = KnowledgeEngine(db).format_entry(entry)
        assert text.index(rendered["risk_notice"]) < text.index("1. action")
        assert text.index("Chapter 2, section 4") < text.index("1. action")
        assert text.index("Succeeded without injury") < text.index("1. action")
        assert text.index("External Reviewer") < text.index("1. action")
        index_html = Path("allspark/templates/index.html").read_text(encoding="utf-8")
        repo_html = Path("allspark/templates/repository.html").read_text(encoding="utf-8")
        assert index_html.index("entry.risk_notice") < index_html.index("entry.steps")
        assert repo_html.index("e.risk_notice") < repo_html.index("${steps ?")
        evidence_index = min(
            repo_html.index("${localEvidence ?"),
            repo_html.index("${externalClaims ?"),
        )
        assert evidence_index < repo_html.index("${steps ?")
        assert "_repoVerificationSelect" in repo_html
    finally:
        set_language(previous, persist=False)
