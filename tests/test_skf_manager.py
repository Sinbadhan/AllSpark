from pathlib import Path

import pytest

from allspark.core.database import Database
from allspark.core.models import KnowledgeEntry
from allspark.services.skf_manager import SKFPackage, _checksum, _entry_checksum, _sanitize_kf_field


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture
def sample_entries():
    return [
        KnowledgeEntry(
            id="sk1", category="water", subcategory="purification",
            priority=1, title="Boil Water", summary="Boil for 3 minutes",
            steps=["Collect", "Heat", "Boil"], prerequisites=["Container"],
            warnings=["Hot!"], verification="expert_verified",
            source="pre_collapse", version=1, language="zh",
        ),
        KnowledgeEntry(
            id="sk2", category="fire", subcategory="starting",
            priority=2, title="Friction Fire", summary="Use bow drill",
            steps=[], prerequisites=[], warnings=[],
            verification="unverified", source="pre_collapse",
            version=1, language="en",
        ),
    ]


class TestEntryChecksum:
    def test_checksum_deterministic(self, sample_entries):
        c1 = _entry_checksum(sample_entries[0])
        c2 = _entry_checksum(sample_entries[0])
        assert c1 == c2

    def test_checksum_differs_for_different_entries(self, sample_entries):
        c1 = _entry_checksum(sample_entries[0])
        c2 = _entry_checksum(sample_entries[1])
        assert c1 != c2

    def test_checksum_format(self, sample_entries):
        c = _entry_checksum(sample_entries[0])
        assert c.startswith("sha256:")
        assert len(c) > 10

    def test_raw_checksum(self):
        c = _checksum("hello")
        assert c.startswith("sha256:")
        import hashlib
        expected = f"sha256:{hashlib.sha256(b'hello').hexdigest()}"
        assert c == expected


class TestSKFExportImport:
    def test_export_and_import(self, db, sample_entries, tmp_path):
        for k in sample_entries:
            db.save_knowledge(k)

        pkg = SKFPackage.from_db(db, spark_id="test-spark")
        export_path = str(tmp_path / "test.skf")
        pkg.export_to_file(export_path)
        assert Path(export_path).exists()

        imported = SKFPackage.import_from_file(export_path)
        assert imported.spark_id == "test-spark"
        assert len(imported.knowledge_entries) == 2

    def test_checksum_in_export(self, db, sample_entries):
        for k in sample_entries:
            db.save_knowledge(k)

        pkg = SKFPackage.from_db(db, spark_id="test-spark")
        data = pkg.to_dict()
        for entry in data["knowledge.json"]:
            assert "checksum" in entry
            assert entry["checksum"].startswith("sha256:")

    def test_validate_good_package(self, db, sample_entries, tmp_path):
        for k in sample_entries:
            db.save_knowledge(k)

        pkg = SKFPackage.from_db(db, spark_id="test-spark")
        export_path = str(tmp_path / "test.skf")
        pkg.export_to_file(export_path)

        imported = SKFPackage.import_from_file(export_path)
        errors = imported.validate()
        assert len(errors) == 0

    def test_validate_missing_spark_id(self):
        pkg = SKFPackage()
        errors = pkg.validate()
        assert any("spark_id" in e for e in errors)


class TestSKFFiltering:
    def test_category_filter(self, db, sample_entries):
        for k in sample_entries:
            db.save_knowledge(k)

        pkg = SKFPackage.from_db(db, spark_id="test", category_filter="water")
        assert len(pkg.knowledge_entries) == 1
        assert pkg.knowledge_entries[0].category == "water"

    def test_language_filter(self, db, sample_entries):
        for k in sample_entries:
            db.save_knowledge(k)

        pkg = SKFPackage.from_db(db, spark_id="test", language="zh")
        assert all(k.language == "zh" for k in pkg.knowledge_entries)


class TestXSSSanitization:
    """SHA-147: untrusted SKF metadata fields must not carry HTML/JS
    metacharacters into the DB (and thence into rendered Web pages)."""

    def test_sanitize_field_strips_html_metacharacters(self):
        assert _sanitize_kf_field('<img id="x">', "id") == "img id=x"
        assert _sanitize_kf_field("<script>alert(1)</script>", "category") == "scriptalert(1)/script"
        assert _sanitize_kf_field("water", "category") == "water"
        # Non-string coerced; None -> default.
        assert _sanitize_kf_field(None, "subcategory", "default") == "default"
        assert _sanitize_kf_field(42, "source") == "42"

    def test_sanitize_field_truncates(self):
        assert len(_sanitize_kf_field("a" * 500, "category")) == 64

    def test_import_strips_xss_payloads_from_metadata(self, tmp_path):
        # Craft a package whose metadata fields carry XSS payloads, export it,
        # then import it back and confirm the metacharacters were stripped at
        # the import boundary (defense-in-depth with template-side escHtml).
        pkg = SKFPackage()
        pkg.spark_id = "xss-test"
        pkg.knowledge_entries = [
            KnowledgeEntry(
                id='<img id="audit-xss-probe">',
                category='<script>alert("xss")</script>',
                subcategory='"><svg onload=alert(1)>',
                priority=1, title="Probe", summary="x",
                steps=[], prerequisites=[], warnings=[],
                verification='<b>expert_verified</b>',
                source='other_spark"',
                version=1, language="zh",
            )
        ]
        export_path = str(tmp_path / "xss.skf")
        pkg.export_to_file(export_path)

        imported = SKFPackage.import_from_file(export_path)
        assert len(imported.knowledge_entries) == 1
        e = imported.knowledge_entries[0]

        # No HTML/JS metacharacters survive into any rendered metadata field.
        for field in (e.id, e.category, e.subcategory, e.verification, e.source):
            assert "<" not in field, f"< in {field!r}"
            assert ">" not in field, f"> in {field!r}"
            assert '"' not in field, f'" in {field!r}'
            assert "'" not in field, f"' in {field!r}"
            assert "&" not in field, f"& in {field!r}"

        # The probe id's text content survives (sanitized, not dropped).
        assert e.id == "img id=audit-xss-probe"

    def test_import_missing_id_falls_back(self, tmp_path):
        # An id made only of metacharacters sanitizes to empty -> a generated
        # spark-id is used instead of crashing (no KeyError on missing id).
        pkg = SKFPackage()
        pkg.spark_id = "missing-id-test"
        pkg.knowledge_entries = [
            KnowledgeEntry(
                id='<>"\'&', category="water", subcategory="purification",
                priority=1, title="T", summary="s", steps=[], prerequisites=[],
                warnings=[], verification="unverified", source="other_spark",
                version=1, language="zh",
            )
        ]
        export_path = str(tmp_path / "noid.skf")
        pkg.export_to_file(export_path)
        e = SKFPackage.import_from_file(export_path).knowledge_entries[0]
        assert e.id.startswith("spark-")
