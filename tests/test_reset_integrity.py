import sqlite3
from pathlib import Path

import pytest

from allspark.core.database import Database
from allspark.core.models import ResetLevel
from allspark.services.reset_manager import ResetManager


@pytest.fixture
def db(tmp_path: Path):
    database = Database(tmp_path / "reset-integrity.db")
    yield database
    database.close()


def _seed_reset_domains(db: Database) -> None:
    db.conn.execute(
        "INSERT INTO knowledge (id, category, subcategory, priority, title) "
        "VALUES ('k1', 'fire', 'ignition', 1, 'Battery ignition')"
    )
    db.conn.execute(
        "INSERT INTO knowledge_fts VALUES "
        "('k1', 'Battery ignition', 'summary', 'steps', 'fire', 'ignition')"
    )
    db.conn.execute(
        "INSERT INTO knowledge_vectors VALUES ('k1', '[0.1, 0.2]', '2026-07-15')"
    )
    db.conn.execute(
        "INSERT INTO diary_entries (id, date, content, created_at) "
        "VALUES ('d1', '2026-07-15', 'private note', '2026-07-15T00:00:00')"
    )
    db.conn.execute(
        "INSERT INTO diary_fts VALUES ('2026-07-15', 'private note', 'private')"
    )
    db.conn.execute(
        "INSERT INTO timeline_events "
        "(id, day, timestamp, event_type, title) "
        "VALUES ('t1', 1, '2026-07-15T00:00:00', 'test', 'Private event')"
    )
    db.conn.execute(
        "INSERT INTO action_plans "
        "(id, warning_id, resource_type, solution_source) "
        "VALUES ('a1', 'water-low', 'water', 'knowledge')"
    )
    db.conn.commit()


def _count(db: Database, table: str) -> int:
    quoted = '"' + table.replace('"', '""') + '"'
    row = db.conn.execute(f"SELECT COUNT(*) AS count FROM {quoted}").fetchone()
    return int(row["count"])


def test_l2_matches_archive_policy_and_preserves_knowledge(db: Database) -> None:
    db.mark_initialized()
    db.conn.execute(
        "INSERT OR REPLACE INTO operating_state VALUES ('language', 'en')"
    )
    db.save_survivor_state("language", "en")
    db.save_survivor_state("name", "Ada")
    db.save_hardware_profile("cpu_arch", "arm64")
    _seed_reset_domains(db)

    result = ResetManager(db).execute_reset(
        ResetLevel.ARCHIVE, force=True, performed_by="test"
    )

    assert result["status"] == "ok"
    for table in (
        "diary_entries",
        "diary_fts",
        "timeline_events",
        "action_plans",
    ):
        assert _count(db, table) == 0, table
    assert _count(db, "knowledge") == 1
    assert _count(db, "knowledge_fts") == 1
    assert _count(db, "knowledge_vectors") == 1
    assert db.is_initialized() is True
    assert db.get_survivor_state() == {"language": "en"}
    assert db.get_hardware_profile()["cpu_arch"] == "arm64"
    assert db.get_reset_logs()[0]["status"] == "accepted"


def test_l3_schema_driven_clear_covers_future_tables_fts_and_audit(db: Database) -> None:
    db.mark_initialized()
    db.conn.execute(
        "INSERT OR REPLACE INTO operating_state VALUES ('language', 'en')"
    )
    _seed_reset_domains(db)
    db.conn.execute("CREATE TABLE future_sensitive_data (secret TEXT NOT NULL)")
    db.conn.execute("INSERT INTO future_sensitive_data VALUES ('erase me')")
    db.conn.commit()
    db.save_reset_log(
        "old-reset",
        1,
        status="accepted",
        performed_at="2026-07-01T00:00:00",
    )

    top_level_tables = db.get_application_tables()
    assert "future_sensitive_data" in top_level_tables
    assert "knowledge_fts" in top_level_tables
    assert "knowledge_fts_data" not in top_level_tables

    result = ResetManager(db).execute_reset(
        ResetLevel.FACTORY, force=True, performed_by="test"
    )

    assert result["status"] == "ok"
    for table in top_level_tables:
        expected = 1 if table in {"operating_state", "reset_log"} else 0
        assert _count(db, table) == expected, table
    assert db.is_initialized() is False
    assert db.conn.execute(
        "SELECT value FROM operating_state WHERE key='language'"
    ).fetchone()["value"] == "en"
    logs = db.get_reset_logs()
    assert len(logs) == 1
    assert logs[0]["level"] == 3
    assert logs[0]["status"] == "accepted"


def test_reset_log_and_cooldown_survive_manager_restart(db: Database) -> None:
    first = ResetManager(db)
    accepted = first.execute_reset(
        ResetLevel.ASSESSMENT, force=True, performed_by="test"
    )
    assert accepted["status"] == "ok"

    restarted = ResetManager(db)
    status = restarted.get_reset_status()
    assert status["last_reset"] is not None
    assert status["can_reset"] is False

    rejected = restarted.execute_reset(
        ResetLevel.ASSESSMENT, performed_by="test"
    )
    assert rejected["status"] == "rejected"
    assert [row["status"] for row in db.get_reset_logs(limit=2)] == [
        "rejected",
        "accepted",
    ]
    assert "force=true" in db.get_reset_logs(limit=2)[1]["reason"]


def test_accepted_audit_failure_rolls_back_reset(db: Database, monkeypatch) -> None:
    db.conn.execute(
        "INSERT INTO diary_entries (id, date, content, created_at) "
        "VALUES ('d1', '2026-07-15', 'keep on failure', '2026-07-15T00:00:00')"
    )
    db.conn.commit()

    def fail_audit(*args, **kwargs):
        raise sqlite3.OperationalError("audit unavailable")

    monkeypatch.setattr(db, "save_reset_log", fail_audit)
    with pytest.raises(sqlite3.OperationalError, match="audit unavailable"):
        ResetManager(db).execute_reset(ResetLevel.ARCHIVE, force=True)

    assert _count(db, "diary_entries") == 1


def test_legacy_reset_log_schema_is_migrated(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE reset_log ("
        "id TEXT PRIMARY KEY, level INTEGER NOT NULL, reason TEXT DEFAULT '', "
        "backup_id TEXT DEFAULT '', performed_by TEXT DEFAULT '', "
        "performed_at TEXT NOT NULL)"
    )
    conn.commit()
    conn.close()

    db = Database(path)
    try:
        columns = {
            row["name"] for row in db.conn.execute("PRAGMA table_info(reset_log)")
        }
        assert "status" in columns
        db.save_reset_log("migrated", 2, status="rejected")
        assert db.get_reset_logs()[0]["status"] == "rejected"
    finally:
        db.close()
