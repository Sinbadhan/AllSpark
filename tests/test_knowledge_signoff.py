"""SHA-148: knowledge expert_verified must be backed by an auditable signoff.

Covers: signoff schema + content-hash invalidation, loader downgrade guard,
verifier-level gating, the real knowledge base holding no unsigned
expert_verified claims, and DB round-trip of the signoff fields.
"""
from allspark.core.database import Database
from allspark.core.models import KnowledgeEntry, compute_content_hash
from allspark.services.knowledge_loader import _dict_to_entry, load_all_knowledge
from allspark.services.knowledge_verifier import KnowledgeVerifier


def _signed_entry() -> KnowledgeEntry:
    e = KnowledgeEntry(
        id="test/water/boil", category="survival", subcategory="water",
        priority=1, title="Boil Water", summary="Boil water to purify it",
        steps=["Boil for 3 min"], warnings=["Hot surface"],
        verification="field_tested", source="pre_collapse", language="zh",
        reviewer="Dr. Survival", qualification="Wilderness MD",
        review_date="2026-07-10", citation="WHO Drinking-water Guidelines",
        signoff_version=1,
    )
    e.content_hash = compute_content_hash(e)
    return e


class TestSignoffSchema:
    def test_unsigned_entry_is_not_signed_off(self):
        e = KnowledgeEntry(
            id="x", category="survival", subcategory="water", priority=1,
            title="T", summary="S",
        )
        assert e.is_signed_off() is False

    def test_signed_entry_is_signed_off(self):
        assert _signed_entry().is_signed_off() is True

    def test_signoff_invalidated_by_content_change(self):
        e = _signed_entry()
        assert e.is_signed_off() is True
        e.summary = "Boil water longer to purify"  # content drifts after signing
        assert e.is_signed_off() is False

    def test_signoff_requires_reviewer_and_version(self):
        e = _signed_entry()
        e.reviewer = ""  # reviewer removed
        assert e.is_signed_off() is False
        e2 = _signed_entry()
        e2.signoff_version = 0  # version removed
        assert e2.is_signed_off() is False

    def test_content_hash_is_deterministic(self):
        e1 = _signed_entry()
        e2 = KnowledgeEntry(
            id="test/water/boil", category="survival", subcategory="water",
            priority=1, title="Boil Water", summary="Boil water to purify it",
            steps=["Boil for 3 min"], warnings=["Hot surface"],
        )
        assert compute_content_hash(e1) == compute_content_hash(e2)


class TestLoaderGuard:
    def test_downgrades_expert_verified_without_signoff(self):
        entry = _dict_to_entry({
            "id": "x", "category": "survival", "subcategory": "water",
            "priority": 1, "title": "T", "summary": "S",
            "verification": "expert_verified", "source": "pre_collapse",
        })
        assert entry.verification == "unverified"
        assert entry.is_signed_off() is False

    def test_keeps_expert_verified_with_valid_signoff(self):
        probe = KnowledgeEntry(
            id="x", category="survival", subcategory="water", priority=1,
            title="T", summary="S",
        )
        entry = _dict_to_entry({
            "id": "x", "category": "survival", "subcategory": "water",
            "priority": 1, "title": "T", "summary": "S",
            "verification": "expert_verified", "source": "pre_collapse",
            "reviewer": "Dr", "qualification": "Wilderness MD",
            "review_date": "2026-07-15", "citation": "Manual section 2",
            "signoff_version": 1,
            "content_hash": compute_content_hash(probe),
        })
        assert entry.verification == "expert_verified"
        assert entry.is_signed_off() is True


class TestVerifierGate:
    def test_unsigned_high_trust_is_unverified(self):
        # A provenance claim without auditable cross-reference or controlled
        # field records cannot become field_tested or expert_verified.
        verifier = KnowledgeVerifier(db=None)
        entry = KnowledgeEntry(
            id="test/water/boil3", category="survival", subcategory="water",
            priority=1, title="Boil Water", summary="Boil water to purify",
            steps=["Boil"], warnings=["Hot"], verification="field_tested",
            source="pre_collapse", language="zh",
        )
        report = verifier.verify_entry(entry)
        assert report.level == "unverified"

    def test_signed_high_trust_gets_expert_verified(self):
        # Expert signoff is a separate controlled evidence path; the skipped
        # cross-reference result is not counted as support.
        verifier = KnowledgeVerifier(db=None)
        report = verifier.verify_entry(_signed_entry())
        assert report.level == "expert_verified"
        assert report.overall_passed is True
        cross_ref = next(result for result in report.results if result.step == "cross_reference")
        assert cross_ref.passed is False
        level = next(result for result in report.results if result.step == "level_assign")
        assert level.details["has_support"] is False


class TestRealKnowledgeBase:
    def test_no_unsigned_expert_verified_in_zh_base(self):
        entries = load_all_knowledge("zh")
        assert len(entries) > 0
        expert = [e for e in entries if e.verification == "expert_verified"]
        assert expert == [], f"{len(expert)} zh entries claim expert_verified"
        assert all(not e.is_signed_off() for e in entries)

    def test_no_unsigned_expert_verified_in_en_base(self):
        entries = load_all_knowledge("en")
        assert len(entries) > 0
        expert = [e for e in entries if e.verification == "expert_verified"]
        assert expert == [], f"{len(expert)} en entries claim expert_verified"


class TestDBRoundtrip:
    def test_signoff_fields_persist(self, tmp_path):
        db = Database(tmp_path / "signoff.db")
        try:
            original = _signed_entry()
            db.save_knowledge(original)
            loaded = db.get_knowledge("test/water/boil")
            assert loaded is not None
            assert loaded.reviewer == "Dr. Survival"
            assert loaded.qualification == "Wilderness MD"
            assert loaded.review_date == "2026-07-10"
            assert loaded.citation == "WHO Drinking-water Guidelines"
            assert loaded.signoff_version == 1
            assert loaded.content_hash == original.content_hash
            assert loaded.is_signed_off() is True
        finally:
            db.close()
