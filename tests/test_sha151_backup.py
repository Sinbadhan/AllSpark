"""SHA-151: data_preservation (backup critical path) branch coverage.

Covers start/stop_auto_save, the auto-save loop, emergency_save, _create_backup,
_cleanup_old_backups, snapshot no-db / not-found / bad-integrity paths, and the
non-main-db _verify_integrity path. Signal handlers and the background thread
are mocked to avoid test side effects.
"""
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from allspark.core.database import Database
from allspark.infrastructure import data_preservation as dp_module
from allspark.infrastructure.data_preservation import DataPreservation


@pytest.fixture
def dp(tmp_path: Path) -> DataPreservation:
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    p = DataPreservation(db=db, db_path=str(db_path))
    yield p
    db.close()


@pytest.fixture
def dp_no_db(tmp_path: Path) -> DataPreservation:
    # Points at a db path that does not exist on disk.
    return DataPreservation(db=None, db_path=str(tmp_path / "missing.db"))


# ─── auto_save start / stop ──────────────────────────────────────────────────


def test_start_auto_save_already_running(dp: DataPreservation, monkeypatch) -> None:
    dp._running = True
    assert dp.start_auto_save() == {"status": "already_running"}


def test_start_and_stop_auto_save(dp: DataPreservation, monkeypatch) -> None:
    monkeypatch.setattr(dp, "_install_signal_handlers", lambda: None)
    monkeypatch.setattr(dp_module.threading, "Thread", MagicMock())
    r = dp.start_auto_save(interval_seconds=10)
    assert r == {"status": "started", "interval_s": 10}
    r2 = dp.stop_auto_save()
    assert r2["status"] == "stopped"


def test_auto_save_loop_one_iteration_then_exits(dp: DataPreservation, monkeypatch) -> None:
    monkeypatch.setattr(dp_module.time, "sleep", lambda s: None)

    def _save_then_stop() -> None:
        dp._save_count += 1
        dp._running = False  # exit after one iteration

    monkeypatch.setattr(dp, "_periodic_save", _save_then_stop)
    dp._running = True
    dp._auto_save_loop()
    assert dp._save_count == 1


def test_auto_save_loop_swallows_periodic_exception(dp: DataPreservation, monkeypatch) -> None:
    monkeypatch.setattr(dp_module.time, "sleep", lambda s: None)
    dp._running = True

    def _boom() -> None:
        dp._running = False
        raise RuntimeError("boom")

    monkeypatch.setattr(dp, "_periodic_save", _boom)
    dp._auto_save_loop()  # must not raise


def test_periodic_save_creates_backup_and_updates_state(dp: DataPreservation) -> None:
    dp._periodic_save()
    assert dp._save_count == 1
    assert dp._last_save_time is not None


# ─── emergency_save ──────────────────────────────────────────────────────────


def test_emergency_save_ok(dp: DataPreservation) -> None:
    r = dp.emergency_save(reason="test")
    assert r["status"] == "ok"
    assert r["integrity"] is True
    assert r["reason"] == "test"


def test_emergency_save_no_db_file(dp_no_db: DataPreservation) -> None:
    assert dp_no_db.emergency_save() == {"status": "no_db_file"}


def test_emergency_save_without_db_object_uses_plain_copy(tmp_path: Path) -> None:
    # db file exists but no db object -> skip WAL checkpoint, plain copy (line 79->86).
    db_path = tmp_path / "solo.db"
    Database(db_path).close()  # create the file
    p = DataPreservation(db=None, db_path=str(db_path))
    r = p.emergency_save(reason="solo")
    assert r["status"] == "ok"


# ─── _create_backup + _cleanup_old_backups ───────────────────────────────────


def test_create_backup_returns_path(dp: DataPreservation) -> None:
    path = dp._create_backup()
    assert path is not None and Path(path).exists()


def test_create_backup_no_db_file_returns_none(dp_no_db: DataPreservation) -> None:
    assert dp_no_db._create_backup() is None


def test_cleanup_old_backups_keeps_max(dp: DataPreservation) -> None:
    dp.backup_dir.mkdir(parents=True, exist_ok=True)
    for i in range(26):
        (dp.backup_dir / f"auto_20260101_0000{i:02d}.db").write_bytes(b"x")
    dp._cleanup_old_backups(max_backups=24)
    assert len(list(dp.backup_dir.glob("auto_*.db"))) == 24


def test_cleanup_old_backups_noop_when_under_max(dp: DataPreservation) -> None:
    dp.backup_dir.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        (dp.backup_dir / f"auto_20260101_0000{i:02d}.db").write_bytes(b"x")
    dp._cleanup_old_backups(max_backups=24)
    assert len(list(dp.backup_dir.glob("auto_*.db"))) == 3


# ─── snapshots: no-db / not-found / bad-integrity ────────────────────────────


def test_create_snapshot_no_db_file(dp_no_db: DataPreservation) -> None:
    assert dp_no_db.create_snapshot(label="x") == {"status": "no_db_file"}


def test_create_snapshot_is_wal_consistent_and_leaves_no_temp_files(
    dp: DataPreservation,
) -> None:
    dp.db.conn.execute("PRAGMA journal_mode=WAL")
    dp.db.conn.execute(
        "INSERT OR REPLACE INTO operating_state VALUES (?, ?)",
        ("sha181_wal", "committed"),
    )
    dp.db.conn.commit()

    result = dp.create_snapshot(label="wal / safe")

    assert result["status"] == "ok"
    assert "/" not in Path(result["path"]).name
    with sqlite3.connect(result["path"]) as conn:
        assert conn.execute(
            "SELECT value FROM operating_state WHERE key='sha181_wal'"
        ).fetchone() == ("committed",)
    assert not list(dp.snapshot_dir.glob(".*.tmp"))


def test_create_snapshot_interruption_publishes_no_partial_artifact(
    dp: DataPreservation, monkeypatch
) -> None:
    def _partial_then_fail(destination: Path) -> None:
        destination.write_bytes(b"partial")
        raise OSError("simulated interruption")

    monkeypatch.setattr(dp, "_copy_database", _partial_then_fail)

    result = dp.create_snapshot(label="interrupted")

    assert result["status"] == "error"
    assert list(dp.snapshot_dir.glob("snapshot_*.db")) == []
    assert list(dp.snapshot_dir.glob("snapshot_*.db.meta")) == []
    assert not list(dp.snapshot_dir.glob(".*.tmp"))


def test_create_snapshot_metadata_publish_failure_rolls_back_snapshot(
    dp: DataPreservation, monkeypatch
) -> None:
    real_replace = dp_module.os.replace

    def _fail_metadata_publish(source: Path, destination: Path) -> None:
        if str(destination).endswith(".db.meta"):
            raise OSError("simulated metadata publish failure")
        real_replace(source, destination)

    monkeypatch.setattr(dp_module.os, "replace", _fail_metadata_publish)

    result = dp.create_snapshot(label="metadata-failure")

    assert result["status"] == "error"
    assert "metadata publish failure" in result["message"]
    assert list(dp.snapshot_dir.glob("snapshot_*.db")) == []
    assert list(dp.snapshot_dir.glob("snapshot_*.db.meta")) == []
    assert not list(dp.snapshot_dir.glob(".*.tmp"))


def test_create_snapshot_rejects_failed_staged_integrity(
    dp: DataPreservation, monkeypatch
) -> None:
    monkeypatch.setattr(dp, "_verify_integrity", lambda _path: False)

    result = dp.create_snapshot(label="bad-integrity")

    assert result == {"status": "error", "message": "Snapshot integrity check failed"}
    assert list(dp.snapshot_dir.glob("snapshot_*.db")) == []
    assert list(dp.snapshot_dir.glob("snapshot_*.db.meta")) == []
    assert not list(dp.snapshot_dir.glob(".*.tmp"))


def test_restore_snapshot_not_found(dp: DataPreservation) -> None:
    r = dp.restore_snapshot("does-not-exist")
    assert r["status"] == "error"
    assert "not found" in r["message"].lower()


def test_restore_snapshot_bad_integrity(dp: DataPreservation, monkeypatch) -> None:
    monkeypatch.setattr(dp, "_verify_integrity", lambda p: False)
    # point at an existing non-snapshot file so the "not found" branch is skipped
    target = dp.db_path
    r = dp.restore_snapshot(str(target))
    assert r["status"] == "error"
    assert "integrity" in r["message"].lower()


def test_restore_rejects_sqlite_valid_checksum_tampering_and_keeps_db_open(
    dp: DataPreservation,
) -> None:
    dp.db.conn.execute(
        "INSERT OR REPLACE INTO operating_state VALUES (?, ?)",
        ("sha181_state", "snapshot"),
    )
    dp.db.conn.commit()
    snapshot = dp.create_snapshot(label="tamper")
    dp.db.conn.execute(
        "UPDATE operating_state SET value=? WHERE key=?",
        ("current", "sha181_state"),
    )
    dp.db.conn.commit()

    with sqlite3.connect(snapshot["path"]) as conn:
        conn.execute(
            "UPDATE operating_state SET value=? WHERE key=?",
            ("tampered-but-valid", "sha181_state"),
        )

    result = dp.restore_snapshot(snapshot["path"])

    assert result["status"] == "error"
    assert "checksum" in result["message"].lower()
    assert dp.db.conn.execute(
        "SELECT value FROM operating_state WHERE key='sha181_state'"
    ).fetchone()[0] == "current"


def test_restore_is_atomic_reopens_database_and_removes_stale_sidecars(
    dp: DataPreservation,
) -> None:
    dp.db.conn.execute(
        "INSERT OR REPLACE INTO operating_state VALUES (?, ?)",
        ("sha181_state", "snapshot"),
    )
    dp.db.conn.commit()
    snapshot = dp.create_snapshot(label="restore-atomic")
    dp.db.conn.execute(
        "UPDATE operating_state SET value=? WHERE key=?",
        ("current", "sha181_state"),
    )
    dp.db.conn.commit()
    Path(f"{dp.db_path}-wal").touch()
    Path(f"{dp.db_path}-shm").touch()

    result = dp.restore_snapshot(snapshot["path"])

    assert result["status"] == "ok"
    assert result["checksum_verified"] is True
    assert dp.db.conn.execute(
        "SELECT value FROM operating_state WHERE key='sha181_state'"
    ).fetchone()[0] == "snapshot"
    assert not Path(f"{dp.db_path}-wal").exists()
    assert not Path(f"{dp.db_path}-shm").exists()
    assert not list(dp.db_path.parent.glob(".*.restore.tmp"))


def test_restore_requires_snapshot_metadata(dp: DataPreservation) -> None:
    snapshot = dp.create_snapshot(label="missing-meta")
    Path(f"{snapshot['path']}.meta").unlink()

    result = dp.restore_snapshot(snapshot["path"])

    assert result == {"status": "error", "message": "Snapshot metadata not found"}


def test_restore_replace_failure_reopens_original_database(
    dp: DataPreservation, monkeypatch
) -> None:
    snapshot = dp.create_snapshot(label="replace-failure")
    real_replace = dp_module.os.replace

    def _fail_restore(source: Path, destination: Path) -> None:
        if str(source).endswith(".restore.tmp"):
            raise OSError("simulated replace failure")
        real_replace(source, destination)

    monkeypatch.setattr(dp_module.os, "replace", _fail_restore)

    result = dp.restore_snapshot(snapshot["path"])

    assert result["status"] == "error"
    assert "replace failure" in result["message"]
    assert dp.db.conn.execute("SELECT 1").fetchone()[0] == 1


def test_verify_integrity_non_main_db_uses_sqlite_connect(dp: DataPreservation) -> None:
    # A snapshot path != main db -> exercises the sqlite3.connect branch (line 199-202).
    snap = dp.create_snapshot(label="verify")
    assert snap["status"] == "ok"
    assert dp._verify_integrity(Path(snap["path"])) is True


def test_verify_integrity_returns_false_on_corrupt_file(dp: DataPreservation, tmp_path: Path) -> None:
    bogus = tmp_path / "bogus.db"
    bogus.write_bytes(b"not a database")
    assert dp._verify_integrity(bogus) is False


# ─── list_snapshots + get_status ─────────────────────────────────────────────


def test_list_snapshots_empty_when_no_dir(dp_no_db: DataPreservation) -> None:
    assert dp_no_db.list_snapshots() == []


def test_get_status_with_dirs_populated(dp: DataPreservation) -> None:
    dp.create_snapshot(label="s1")
    dp._create_backup()
    status = dp.get_status()
    assert status["snapshot_count"] >= 1
    assert status["backup_count"] >= 1
    assert status["db_size_mb"] >= 0


# ─── remaining branches: no-db-object, loop-sleep-exit, startup paths ────────


@pytest.fixture
def dp_no_obj(tmp_path: Path) -> DataPreservation:
    # db file exists on disk, but no db object attached (exercises the
    # `if self.db` false branches in _create_backup / create_snapshot / restore).
    db_path = tmp_path / "solo.db"
    Database(db_path).close()
    return DataPreservation(db=None, db_path=str(db_path))


def test_stop_auto_save_with_no_thread(dp: DataPreservation, monkeypatch) -> None:
    # _save_thread is None -> skip join (covers [51,53]).
    monkeypatch.setattr(dp, "_install_signal_handlers", lambda: None)
    dp._save_thread = None
    r = dp.stop_auto_save()
    assert r["status"] == "stopped"


def test_auto_save_loop_exits_when_running_flips_during_sleep(dp: DataPreservation, monkeypatch) -> None:
    # _running set False inside sleep -> `if self._running` at line 59 is False (covers [59,57]).
    def _sleep_then_stop(_s):
        dp._running = False
    monkeypatch.setattr(dp_module.time, "sleep", _sleep_then_stop)
    dp._running = True
    dp._auto_save_loop()


def test_create_backup_no_db_object_file_exists(dp_no_obj: DataPreservation) -> None:
    # db file exists, no db object -> skip commit, plain copy (covers [103,108]).
    path = dp_no_obj._create_backup()
    assert path is not None and Path(path).exists()


def test_create_snapshot_no_db_object_file_exists(dp_no_obj: DataPreservation) -> None:
    r = dp_no_obj.create_snapshot(label="noobj")
    assert r["status"] == "ok"


def test_restore_snapshot_by_label_glob(dp: DataPreservation) -> None:
    # Restore via a label substring that matches via glob (covers [175,177]).
    dp.create_snapshot(label="globby")
    r = dp.restore_snapshot("globby")
    assert r["status"] == "ok"


def test_restore_snapshot_no_db_object_skips_close(dp_no_obj: DataPreservation) -> None:
    # No db object -> skip db.conn.close() (covers [183,189]).
    snap = dp_no_obj.create_snapshot(label="restore")
    r = dp_no_obj.restore_snapshot(snap["path"])
    assert r["status"] == "ok"


def test_get_status_no_db_file(dp_no_db: DataPreservation) -> None:
    status = dp_no_db.get_status()
    assert status["db_size_mb"] == 0
    assert status["backup_count"] == 0


def test_startup_check_no_db_file(dp_no_db: DataPreservation) -> None:
    r = dp_no_db.startup_integrity_check()
    assert r["db_file_exists"] is False
    assert any("does not exist" in w.lower() for w in r["warnings"])


def test_startup_check_no_db_object_uses_verify(dp_no_obj: DataPreservation) -> None:
    r = dp_no_obj.startup_integrity_check()
    assert r["db_file_exists"] is True
    assert r["integrity_ok"] is True


def test_startup_check_bad_integrity(dp: DataPreservation, monkeypatch) -> None:
    monkeypatch.setattr(dp.db, "check_integrity", lambda: False)
    r = dp.startup_integrity_check()
    assert r["integrity_ok"] is False
    assert any("integrity" in w.lower() for w in r["warnings"])


def test_startup_check_missing_tables(tmp_path: Path) -> None:
    # A db that passes integrity but is missing expected tables (covers [299,300]).
    db_path = tmp_path / "partial.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE foo (x INTEGER)")
    conn.commit()
    conn.close()
    p = DataPreservation(db=None, db_path=str(db_path))
    r = p.startup_integrity_check()
    assert r["integrity_ok"] is True
    assert any("missing tables" in w.lower() for w in r["warnings"])
