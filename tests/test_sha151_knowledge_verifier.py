"""SHA-151: knowledge_verifier line-coverage tests (criterion 1: total line >=75%).

Covers the 5 verification steps (format/source/consistency/cross-ref/level-assign),
the contradiction detector, ref dedup, and KnowledgeSigner sign/verify flows.
"""

from allspark.core.database import Database
from allspark.core.models import KnowledgeEntry
from allspark.services.knowledge_verifier import (
    KnowledgeSigner,
    KnowledgeVerifier,
    VerificationLevel,
)


def _entry(id="v1", title="T", summary="S", category="survival", priority=1,
           source="pre_collapse", verification="unverified", steps=None,
           warnings=None, reviewer="", signoff_version=0, content_hash="") -> KnowledgeEntry:
    return KnowledgeEntry(
        id=id, category=category, subcategory="sub", priority=priority,
        title=title, summary=summary, steps=steps or [], prerequisites=[],
        warnings=warnings or [], verification=verification, source=source,
        version=1, language="zh", reviewer=reviewer, signoff_version=signoff_version,
        content_hash=content_hash,
    )


def test_verify_entry_good_entry_passes():
    v = KnowledgeVerifier()
    report = v.verify_entry(_entry())
    assert report.overall_passed is True
    assert report.level  # some level assigned


def test_format_check_missing_required_field():
    v = KnowledgeVerifier()
    report = v.verify_entry(_entry(title=""))  # missing title
    assert not report.overall_passed


def test_format_check_invalid_priority():
    v = KnowledgeVerifier()
    report = v.verify_entry(_entry(priority=9))
    assert not report.overall_passed


def test_format_check_unusual_category_warning():
    v = KnowledgeVerifier()
    report = v.verify_entry(_entry(category="weird"))
    # Format passes but with a warning about the unusual category.
    fmt = next(r for r in report.results if r.step == "format_check")
    assert fmt.passed is True
    assert any("weird" in w for w in fmt.details.get("warnings", []))


def test_source_check_trust_levels():
    v = KnowledgeVerifier()
    for source, expected in [("pre_collapse", "high"), ("other_spark", "moderate"), ("unknown", "low")]:
        r = v.verify_entry(_entry(source=source))
        src = next(x for x in r.results if x.step == "source_check")
        assert src.details["trust_level"] == expected


def test_source_check_verification_overrides():
    v = KnowledgeVerifier()
    # unknown source but expert_verified -> high trust.
    r = v.verify_entry(_entry(source="unknown", verification="expert_verified"))
    src = next(x for x in r.results if x.step == "source_check")
    assert src.details["trust_level"] == "high"


def test_consistency_check_no_db_skips():
    v = KnowledgeVerifier()
    r = v.verify_entry(_entry())
    cons = next(x for x in r.results if x.step == "consistency_check")
    assert cons.details.get("skipped") is True


def test_consistency_check_detects_summary_conflict(tmp_path):
    db = Database(tmp_path / "kv.db")
    existing = _entry(id="c1", summary="必须煮沸")
    db.save_knowledge(existing)
    v = KnowledgeVerifier(db=db)
    # New entry with same id but contradictory summary.
    report = v.verify_entry(_entry(id="c1", summary="不要煮沸"))
    cons = next(x for x in report.results if x.step == "consistency_check")
    assert not cons.passed
    db.close()


def test_consistency_check_warning_conflict_across_entries(tmp_path):
    db = Database(tmp_path / "kv2.db")
    db.save_knowledge(_entry(id="a", summary="ok", category="survival", warnings=["禁止饮用"]))
    v = KnowledgeVerifier(db=db)
    # Different id, same category, contradictory warning.
    report = v.verify_entry(_entry(id="b", summary="x", category="survival", warnings=["可以饮用"]))
    cons = next(x for x in report.results if x.step == "consistency_check")
    assert not cons.passed
    db.close()


def test_cross_reference_no_db_skips():
    v = KnowledgeVerifier()
    r = v.verify_entry(_entry())
    cr = next(x for x in r.results if x.step == "cross_reference")
    assert cr.details.get("skipped") is True


def test_cross_reference_finds_support(tmp_path):
    db = Database(tmp_path / "kv3.db")
    db.save_knowledge(_entry(id="s1", title="water boiling", summary="purify", category="survival"))
    db.save_knowledge(_entry(id="s2", title="water boiling method", summary="purify water", category="survival"))
    v = KnowledgeVerifier(db=db)
    r = v.verify_entry(_entry(id="s2", title="water boiling", summary="purify", category="survival"))
    cr = next(x for x in r.results if x.step == "cross_reference")
    assert cr.details["supporting_count"] >= 1
    db.close()


def test_level_assign_conflict_when_consistency_fails(tmp_path):
    db = Database(tmp_path / "kv4.db")
    db.save_knowledge(_entry(id="c1", summary="必须煮沸"))
    v = KnowledgeVerifier(db=db)
    report = v.verify_entry(_entry(id="c1", summary="不要煮沸"))
    assert report.level == VerificationLevel.CONFLICT.value
    db.close()


def test_level_assign_unverified_for_low_trust():
    v = KnowledgeVerifier()
    r = v.verify_entry(_entry(source="unknown"))
    # low trust, no db support -> unverified (or partially_verified if keywords<3)
    assert r.level in (VerificationLevel.UNVERIFIED.value, VerificationLevel.PARTIALLY_VERIFIED.value)


def test_is_contradictory_negation_patterns():
    v = KnowledgeVerifier()
    assert v._is_contradictory("不要喝水", "应该喝水") is True
    assert v._is_contradictory("do not boil", "must boil") is True
    assert v._is_contradictory("boil water", "clean water") is False
    assert v._is_contradictory("", "something") is False


def test_deduplicate_refs():
    v = KnowledgeVerifier()
    refs = [{"id": "a"}, {"id": "b"}, {"id": "a"}, {"id": "c"}]
    assert len(v._deduplicate_refs(refs)) == 3


def test_verify_batch():
    v = KnowledgeVerifier()
    reports = v.verify_batch([_entry("a"), _entry("b")])
    assert len(reports) == 2


# ─── KnowledgeSigner ────────────────────────────────────────────────────────


def test_signer_derive_key_with_db(tmp_path):
    db = Database(tmp_path / "sig.db")
    s = KnowledgeSigner(db=db)
    sig = s.sign_entry(_entry("k"))
    assert isinstance(sig, str) and len(sig) == 64  # hex sha256
    db.close()


def test_signer_derive_key_without_db():
    s = KnowledgeSigner()
    sig = s.sign_entry(_entry("k"))
    assert len(sig) == 64


def test_signer_verify_match_and_mismatch():
    s = KnowledgeSigner(secret_key="secret")
    e = _entry("k")
    sig = s.sign_entry(e)
    assert s.verify_entry(e, sig) is True
    assert s.verify_entry(e, "wrong") is False


def test_signer_explicit_secret_key():
    s = KnowledgeSigner(secret_key="my-secret")
    assert s._key == b"my-secret"


def test_sign_batch_and_verify_batch():
    s = KnowledgeSigner(secret_key="secret")
    entries = [_entry("a"), _entry("b")]
    sigs = s.sign_batch(entries)
    assert set(sigs.keys()) == {"a", "b"}
    results = s.verify_batch(entries, sigs)
    assert all(results.values())
    # Missing signature -> False.
    results2 = s.verify_batch(entries, {"a": sigs["a"]})
    assert results2["b"] is False


def test_signer_verify_tampered_entry_fails():
    s = KnowledgeSigner(secret_key="secret")
    e = _entry("k", title="original")
    sig = s.sign_entry(e)
    e.title = "tampered"
    assert s.verify_entry(e, sig) is False
