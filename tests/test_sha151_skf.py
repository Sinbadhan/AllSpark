"""SHA-151: skf_manager (SKF critical path) branch coverage.

Covers from_db include/filter branches, import_from_file zip-content branches
(missing knowledge/experience/local, checksum mismatch, no stored checksum),
validate error paths, and import_skf skip-duplicate / verify / validation-error
paths.
"""
import json
import zipfile
from pathlib import Path

import pytest

from allspark.core.database import Database
from allspark.core.models import ExperienceLog, KnowledgeEntry, MapPOI
from allspark.services.knowledge_verifier import KnowledgeVerifier
from allspark.services.skf_manager import SKFPackage, import_skf


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "skf.db")
    yield database
    database.close()


def _entry(id: str = "k1", title: str = "T", summary: str = "S", priority: int = 1,
           category: str = "water", language: str = "zh") -> KnowledgeEntry:
    return KnowledgeEntry(
        id=id, category=category, subcategory="sub", priority=priority,
        title=title, summary=summary, steps=[], prerequisites=[], warnings=[],
        verification="unverified", source="pre_collapse", version=1, language=language,
    )


def _craft_zip(path: Path, files: dict[str, object]) -> str:
    """Write a zip with the given name->content (content json-dumped unless str)."""
    with zipfile.ZipFile(str(path), "w") as zf:
        for name, content in files.items():
            body = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            zf.writestr(name, body)
    return str(path)


def _manifest(spark_id: str = "craft", version: str = "1.0") -> dict:
    return {"skf": {"version": version, "spark_id": spark_id, "created": "2026-01-01",
                    "stats": {"knowledge_count": 0, "experience_count": 0, "local_data_count": 0}},
            "metadata": {}}


# ─── from_db include/filter branches ─────────────────────────────────────────


def test_from_db_excludes_knowledge(db: Database) -> None:
    db.save_knowledge(_entry())
    pkg = SKFPackage.from_db(db, spark_id="s", include_knowledge=False)
    assert pkg.knowledge_entries == []


def test_from_db_excludes_experience(db: Database) -> None:
    db.save_experience(ExperienceLog(id="e1", timestamp="t", event="ev", outcome="ok"))
    pkg = SKFPackage.from_db(db, spark_id="s", include_experience=False)
    assert pkg.experience_log == []


def test_from_db_excludes_local_and_includes_pois(db: Database) -> None:
    db.save_poi(MapPOI(id="p1", name="cave", type="landmark"))
    pkg_no_local = SKFPackage.from_db(db, spark_id="s", include_local=False)
    assert pkg_no_local.local_data == []
    pkg_with_local = SKFPackage.from_db(db, spark_id="s", include_local=True)
    assert len(pkg_with_local.local_data) == 1


def test_from_db_priority_max_below_3(db: Database) -> None:
    db.save_knowledge(_entry(id="a", priority=0))
    db.save_knowledge(_entry(id="b", priority=3))
    pkg = SKFPackage.from_db(db, spark_id="s", priority_max=1)
    ids = {k.id for k in pkg.knowledge_entries}
    assert "a" in ids and "b" not in ids


# ─── to_dict / export with experience + local_data ───────────────────────────


def test_to_dict_includes_experience_and_export_writes_local(db: Database, tmp_path: Path) -> None:
    db.save_knowledge(_entry())
    db.save_experience(ExperienceLog(id="e1", timestamp="t", event="ev", outcome="ok"))
    db.save_poi(MapPOI(id="p1", name="cave", type="landmark"))
    pkg = SKFPackage.from_db(db, spark_id="s")
    data = pkg.to_dict()
    assert len(data["experience.json"]) == 1  # covers the experience loop (161-162)

    # export with local_data present -> writes local_data.json (covers [200,201]).
    export_path = tmp_path / "with_local.skf"
    pkg.export_to_file(str(export_path))
    with zipfile.ZipFile(str(export_path)) as zf:
        assert "local_data.json" in zf.namelist()


# ─── import_from_file: zip-content branches ──────────────────────────────────


def test_import_zip_with_no_knowledge_no_experience_no_local(tmp_path: Path) -> None:
    path = _craft_zip(tmp_path / "bare.skf", {"manifest.json": _manifest()})
    pkg = SKFPackage.import_from_file(str(path))
    assert pkg.knowledge_entries == []
    assert pkg.experience_log == []
    assert pkg.local_data == []


def test_import_zip_with_experience_and_local(tmp_path: Path) -> None:
    path = _craft_zip(tmp_path / "full.skf", {
        "manifest.json": _manifest(),
        "experience.json": [{"id": "e1", "timestamp": "t", "event": "ev", "outcome": "ok", "lesson": ""}],
        "local_data.json": [{"type": "map_poi", "data": {"id": "p1", "name": "x"}}],
    })
    pkg = SKFPackage.import_from_file(str(path))
    assert len(pkg.experience_log) == 1
    assert len(pkg.local_data) == 1


def test_import_checksum_mismatch_recorded(tmp_path: Path) -> None:
    path = _craft_zip(tmp_path / "mismatch.skf", {
        "manifest.json": _manifest(),
        "knowledge.json": [{
            "id": "k1", "category": "water", "subcategory": "s", "priority": 1,
            "title": "T", "content": {"summary": "S", "steps": [], "prerequisites": [], "warnings": []},
            "verification": "unverified", "source": "pre_collapse", "version": 1, "language": "zh",
            "checksum": "sha256:WRONG",
        }],
    })
    pkg = SKFPackage.import_from_file(str(path))
    errors = pkg.validate()
    assert any("checksum" in e.lower() for e in errors)


def test_import_entry_without_stored_checksum_skips_check(tmp_path: Path) -> None:
    # No "checksum" field -> the stored_checksum truthy check is false (covers [250,248]).
    path = _craft_zip(tmp_path / "nochecksum.skf", {
        "manifest.json": _manifest(),
        "knowledge.json": [{
            "id": "k1", "category": "water", "subcategory": "s", "priority": 1,
            "title": "T", "content": {"summary": "S", "steps": [], "prerequisites": [], "warnings": []},
            "verification": "unverified", "source": "pre_collapse", "version": 1, "language": "zh",
        }],
    })
    pkg = SKFPackage.import_from_file(str(path))
    assert pkg.validate() == []  # no checksum error


# ─── validate error paths ────────────────────────────────────────────────────


def _pkg_with(entries=None, experiences=None, version: str = "1.0", spark_id: str = "s") -> SKFPackage:
    pkg = SKFPackage()
    pkg.spark_id = spark_id
    pkg.version = version
    pkg.knowledge_entries = entries or []
    pkg.experience_log = experiences or []
    return pkg


def test_validate_missing_version() -> None:
    pkg = _pkg_with(version="")
    assert any("version" in e.lower() for e in pkg.validate())


def test_validate_propagates_checksum_errors() -> None:
    pkg = _pkg_with()
    pkg._checksum_errors = ["bogus mismatch"]
    assert "bogus mismatch" in pkg.validate()


def test_validate_missing_and_duplicate_id() -> None:
    pkg = _pkg_with(entries=[
        _entry(id="", title="T", summary="S"),
        _entry(id="dup", title="T2", summary="S2"),
        _entry(id="dup", title="T3", summary="S3"),
    ])
    errors = pkg.validate()
    assert any("missing id" in e.lower() for e in errors)
    assert any("duplicate" in e.lower() for e in errors)


def test_validate_missing_title_summary_and_bad_priority() -> None:
    pkg = _pkg_with(entries=[_entry(id="k", title="", summary="", priority=9)])
    errors = pkg.validate()
    assert len(errors) >= 3  # title + summary + priority


def test_validate_experience_missing_event() -> None:
    pkg = _pkg_with(experiences=[ExperienceLog(id="e1", timestamp="t", event="", outcome="ok")])
    errors = pkg.validate()
    assert len(errors) >= 1  # missing-event error (i18n message, assert via id instead)
    assert any("e1" in e for e in errors)


def test_validate_experience_with_event_no_error() -> None:
    # Experience with a non-empty event -> no error (covers the loop no-error arc [321,320]).
    pkg = _pkg_with(experiences=[ExperienceLog(id="e1", timestamp="t", event="ev", outcome="ok")])
    errors = pkg.validate()
    assert not any("e1" in e for e in errors)


def test_get_stats_aggregates_categories() -> None:
    # Covers the categories loop in get_stats (lines 328-331).
    pkg = _pkg_with(entries=[_entry(id="a", category="water"), _entry(id="b", category="fire"),
                             _entry(id="c", category="water")])
    stats = pkg.get_stats()
    assert stats["categories"]["water"] == 2
    assert stats["categories"]["fire"] == 1
    assert stats["knowledge_count"] == 3


def test_import_from_file_raises_on_missing_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        SKFPackage.import_from_file(str(tmp_path / "nope.skf"))


def test_import_skf_overwrites_when_existing_is_older(db: Database, tmp_path: Path) -> None:
    # Existing version=1; imported version=2 -> existing.version < k.version -> overwrite (covers [369,372]).
    db.save_knowledge(_entry(id="k1", title="old", summary="S", priority=1))
    newer = _entry(id="k1", title="new", summary="S", priority=1)
    newer.version = 2
    pkg = SKFPackage()
    pkg.spark_id = "s"
    pkg.knowledge_entries = [newer]
    path = tmp_path / "newer.skf"
    pkg.export_to_file(str(path))
    r = import_skf(db, str(path), verify=True, skip_duplicates=True)
    assert r["status"] == "ok"
    assert r["imported"]["knowledge"] == 1
    assert r["imported"]["skipped"] == 0


def test_import_skf_no_skip_duplicates_overwrites(db: Database, tmp_path: Path) -> None:
    # skip_duplicates=False -> skip the version check entirely (covers [366,372]).
    db.save_knowledge(_entry(id="k1", title="old", summary="S", priority=1))
    pkg = SKFPackage()
    pkg.spark_id = "s"
    pkg.knowledge_entries = [_entry(id="k1", title="new", summary="S", priority=1)]
    path = tmp_path / "noskip.skf"
    pkg.export_to_file(str(path))
    r = import_skf(db, str(path), verify=True, skip_duplicates=False)
    assert r["imported"]["knowledge"] == 1


def test_import_skf_ignores_non_map_poi_local(db: Database, tmp_path: Path) -> None:
    # local_data item whose type != "map_poi" is skipped (covers [381,380]).
    pkg = SKFPackage()
    pkg.spark_id = "s"
    pkg.local_data = [{"type": "unknown", "data": {"id": "x"}}]
    path = tmp_path / "unk.skf"
    pkg.export_to_file(str(path))
    r = import_skf(db, str(path), verify=True)
    assert r["imported"]["local_data"] == 0


def test_import_skf_imports_experience_and_pois(db: Database, tmp_path: Path) -> None:
    # Covers import_skf experience loop ([376,377]) + local_data map_poi ([380,381]).
    pkg = SKFPackage()
    pkg.spark_id = "s"
    pkg.knowledge_entries = [_entry(id="k1")]
    pkg.experience_log = [ExperienceLog(id="e1", timestamp="t", event="ev", outcome="ok")]
    pkg.local_data = [{"type": "map_poi", "data": {"id": "p1", "name": "cave", "type": "landmark"}}]
    path = tmp_path / "full.skf"
    pkg.export_to_file(str(path))
    r = import_skf(db, str(path), verify=True)
    assert r["status"] == "ok"
    assert r["imported"]["experience"] == 1
    assert r["imported"]["local_data"] == 1
    assert db.get_all_pois() and db.get_all_pois()[0].name == "cave"


# ─── import_skf: verify / skip_duplicates / validation_error ─────────────────


def test_import_skf_returns_validation_error_when_invalid(db: Database, tmp_path: Path) -> None:
    pkg = _pkg_with(entries=[_entry(id="k", title="", summary="")])  # invalid: no title/summary
    path = tmp_path / "invalid.skf"
    pkg.export_to_file(str(path))
    r = import_skf(db, str(path), verify=True)
    assert r["status"] == "validation_error"
    assert r["errors"]


def test_import_skf_skip_duplicates_older_version(db: Database, tmp_path: Path) -> None:
    db.save_knowledge(_entry(id="k1", title="T", summary="S", priority=1))
    # exported package has version=1; existing also version=1 -> skipped (existing >= new).
    pkg = SKFPackage()
    pkg.spark_id = "s"
    pkg.knowledge_entries = [_entry(id="k1", title="T", summary="S", priority=1)]
    path = tmp_path / "dup.skf"
    pkg.export_to_file(str(path))
    r = import_skf(db, str(path), verify=True, skip_duplicates=True)
    assert r["status"] == "ok"
    assert r["imported"]["skipped"] == 1
    assert r["imported"]["knowledge"] == 0


def test_import_skf_without_verify_imports_anyway(db: Database, tmp_path: Path) -> None:
    pkg = _pkg_with(entries=[_entry(id="k9", title="", summary="")])  # would fail validation
    path = tmp_path / "noverify.skf"
    pkg.export_to_file(str(path))
    r = import_skf(db, str(path), verify=False)
    assert r["status"] == "ok"
    assert r["imported"]["knowledge"] == 1


@pytest.mark.parametrize("verify", [True, False])
@pytest.mark.parametrize("claim", ["expert_verified", "field_tested", "cross_ref"])
def test_malicious_skf_verification_claim_is_unverified_at_rest(
    db: Database, tmp_path: Path, verify: bool, claim: str
) -> None:
    entry = _entry(id=f"malicious-{claim}")
    entry.source = "pre_collapse"
    entry.verification = claim
    pkg = _pkg_with(entries=[entry], spark_id="attacker")
    path = tmp_path / f"malicious-{claim}-{verify}.skf"
    pkg.export_to_file(str(path))

    result = import_skf(db, str(path), verify=verify, skip_duplicates=False)

    assert result["status"] == "ok"
    persisted = db.get_knowledge(entry.id)
    assert persisted is not None
    assert persisted.source == "other_spark"
    assert persisted.verification == "unverified"
    assert KnowledgeVerifier(db=db).verify_entry(persisted).level == "unverified"
