import sqlite3
import threading
from pathlib import Path

import pytest

from allspark.core.database import CURRENT_SCHEMA_VERSION, Database


def _version(path: Path) -> int:
    connection = sqlite3.connect(path)
    try:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])
    finally:
        connection.close()


def _legacy_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE resources (
                type TEXT PRIMARY KEY, current_amount REAL NOT NULL,
                unit TEXT NOT NULL, daily_consumption REAL DEFAULT 0,
                daily_intake REAL DEFAULT 0,
                estimated_remaining_hours REAL DEFAULT 0,
                last_updated TEXT NOT NULL
            );
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY, phase INTEGER NOT NULL,
                priority INTEGER NOT NULL, title TEXT NOT NULL,
                description TEXT DEFAULT '', status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE knowledge (
                id TEXT PRIMARY KEY, category TEXT NOT NULL,
                subcategory TEXT NOT NULL, priority INTEGER NOT NULL,
                title TEXT NOT NULL, summary TEXT DEFAULT '',
                steps TEXT DEFAULT '[]', prerequisites TEXT DEFAULT '[]',
                warnings TEXT DEFAULT '[]', verification TEXT DEFAULT 'unverified',
                source TEXT DEFAULT 'pre_collapse', version INTEGER DEFAULT 1
            );
            CREATE TABLE map_pois (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL,
                description TEXT DEFAULT '', distance_km REAL DEFAULT 0,
                direction TEXT DEFAULT '', notes TEXT DEFAULT '',
                discovered_at TEXT NOT NULL, verified INTEGER DEFAULT 0
            );
            CREATE TABLE reset_log (
                id TEXT PRIMARY KEY, level INTEGER NOT NULL,
                reason TEXT DEFAULT '', backup_id TEXT DEFAULT '',
                performed_by TEXT DEFAULT '', performed_at TEXT NOT NULL
            );
            INSERT INTO resources
                (type, current_amount, unit, daily_consumption, daily_intake,
                 estimated_remaining_hours, last_updated)
            VALUES ('water', 8, 'L', 2, 0, 96, 'legacy');
            """
        )
        connection.commit()
    finally:
        connection.close()


def test_fresh_database_is_versioned_without_migration_backup(tmp_path: Path) -> None:
    path = tmp_path / "fresh.db"
    database = Database(path)
    database.close()

    assert _version(path) == CURRENT_SCHEMA_VERSION
    assert list(tmp_path.glob("fresh.db.pre-v*.bak")) == []


def test_unversioned_legacy_database_upgrades_data_and_creates_backup(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy.db"
    _legacy_database(path)

    database = Database(path)
    row = database.conn.execute(
        "SELECT amount_known, rate_basis, source FROM resources WHERE type='water'"
    ).fetchone()
    database.close()

    assert _version(path) == CURRENT_SCHEMA_VERSION
    assert tuple(row) == (0, "unknown", "migration")
    backups = list(tmp_path.glob("legacy.db.pre-v0*.bak"))
    assert len(backups) == 1
    assert _version(backups[0]) == 0
    assert backups[0].stat().st_mode & 0o777 == 0o600


def test_failed_migration_rolls_back_schema_and_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "broken.db"
    _legacy_database(path)

    def fail_after_write(self: Database) -> None:
        self.conn.execute("CREATE TABLE should_rollback (id INTEGER)")
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr(Database, "_migrate", fail_after_write)
    with pytest.raises(RuntimeError, match="injected migration failure"):
        Database(path)

    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        marker = connection.execute(
            "SELECT name FROM sqlite_master WHERE name='should_rollback'"
        ).fetchone()
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(resources)")
        }
    finally:
        connection.close()
    assert marker is None
    assert "amount_known" not in columns
    assert len(list(tmp_path.glob("broken.db.pre-v0*.bak"))) == 1


def test_future_schema_is_rejected_without_modification(tmp_path: Path) -> None:
    path = tmp_path / "future.db"
    connection = sqlite3.connect(path)
    connection.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION + 1}")
    connection.execute("CREATE TABLE future_data (value TEXT)")
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match="newer than supported"):
        Database(path)

    assert _version(path) == CURRENT_SCHEMA_VERSION + 1
    assert list(tmp_path.glob("future.db.pre-v*.bak")) == []


def test_reopen_is_idempotent_and_concurrent_initialization_converges(
    tmp_path: Path,
) -> None:
    existing = tmp_path / "existing.db"
    first = Database(existing)
    first.close()
    second = Database(existing)
    second.close()
    assert _version(existing) == CURRENT_SCHEMA_VERSION

    concurrent = tmp_path / "concurrent.db"
    errors: list[Exception] = []

    def open_database() -> None:
        try:
            database = Database(concurrent)
            database.close()
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=open_database) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert _version(concurrent) == CURRENT_SCHEMA_VERSION
