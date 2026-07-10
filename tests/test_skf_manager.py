from pathlib import Path

import pytest

from allspark.core.database import Database
from allspark.core.models import KnowledgeEntry
from allspark.services.skf_manager import SKFPackage, _checksum, _entry_checksum


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
