import os
import sqlite3
import stat
from pathlib import Path

import pytest

from allspark.core.database import Database
from allspark.core.storage_security import StoragePermissionError
from allspark.infrastructure.data_preservation import DataPreservation

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX mode contract")


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_default_managed_storage_migrates_existing_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / ".allspark"
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    db_path = root / "data.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE legacy (value TEXT)")
    db_path.chmod(0o644)
    Path(f"{db_path}-wal").touch(mode=0o644)
    Path(f"{db_path}-shm").touch(mode=0o644)

    monkeypatch.setattr("allspark.core.config.DEFAULT_DB_DIR", root)
    monkeypatch.setattr("allspark.core.config.DEFAULT_DB_PATH", db_path)
    database = Database()
    try:
        assert _mode(root) == 0o700
        for path in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
            assert _mode(path) == 0o600
    finally:
        database.close()


def test_new_custom_database_parent_is_private(tmp_path: Path) -> None:
    db_path = tmp_path / "new-private-root" / "data.db"
    database = Database(db_path)
    try:
        assert _mode(db_path.parent) == 0o700
        assert _mode(db_path) == 0o600
    finally:
        database.close()


def test_custom_database_rejects_parent_writable_by_other_accounts(
    tmp_path: Path,
) -> None:
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir(mode=0o777)
    unsafe.chmod(0o777)

    with pytest.raises(StoragePermissionError, match="unsafe|不安全"):
        Database(unsafe / "data.db")


def test_custom_database_rejects_writable_ancestor_above_private_parent(
    tmp_path: Path,
) -> None:
    unsafe_ancestor = tmp_path / "unsafe-ancestor"
    unsafe_ancestor.mkdir(mode=0o777)
    unsafe_ancestor.chmod(0o777)

    with pytest.raises(StoragePermissionError, match="ancestor|祖先"):
        Database(unsafe_ancestor / "private" / "data.db")


def test_custom_database_allows_sticky_shared_ancestor(tmp_path: Path) -> None:
    sticky_ancestor = tmp_path / "sticky-shared"
    sticky_ancestor.mkdir(mode=0o1777)
    sticky_ancestor.chmod(0o1777)
    db_path = sticky_ancestor / "private" / "data.db"

    database = Database(db_path)
    try:
        assert _mode(sticky_ancestor) == 0o1777
        assert _mode(db_path.parent) == 0o700
        assert _mode(db_path) == 0o600
    finally:
        database.close()


def test_database_rejects_symlinked_parent_under_sticky_ancestor(
    tmp_path: Path,
) -> None:
    sticky_ancestor = tmp_path / "sticky-links"
    sticky_ancestor.mkdir(mode=0o1777)
    sticky_ancestor.chmod(0o1777)
    target = tmp_path / "redirect-target"
    target.mkdir(mode=0o700)
    linked_parent = sticky_ancestor / "linked-parent"
    linked_parent.symlink_to(target, target_is_directory=True)

    with pytest.raises(StoragePermissionError, match="symbolic|符号链接"):
        Database(linked_parent / "data.db")
    assert not (target / "data.db").exists()


def test_database_rejects_symlink_file(tmp_path: Path) -> None:
    real_path = tmp_path / "real.db"
    real_path.touch(mode=0o600)
    link_path = tmp_path / "linked.db"
    link_path.symlink_to(real_path)

    with pytest.raises(StoragePermissionError):
        Database(link_path)


def test_sqlite_wal_and_shm_inherit_private_database_mode(tmp_path: Path) -> None:
    database = Database(tmp_path / "wal.db")
    try:
        assert database.conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        database.conn.execute(
            "INSERT OR REPLACE INTO operating_state VALUES ('privacy', 'private')"
        )
        database.conn.commit()
        assert _mode(database.db_path) == 0o600
        assert _mode(Path(f"{database.db_path}-wal")) == 0o600
        assert _mode(Path(f"{database.db_path}-shm")) == 0o600
    finally:
        database.close()


def test_backup_snapshot_metadata_and_restore_remain_private(tmp_path: Path) -> None:
    db_path = tmp_path / "data.db"
    database = Database(db_path)
    preservation = DataPreservation(db=database)
    try:
        emergency = preservation.emergency_save("privacy")
        automatic = preservation._create_backup()
        snapshot = preservation.create_snapshot("privacy")
        assert automatic is not None

        assert _mode(preservation.backup_dir) == 0o700
        assert _mode(preservation.snapshot_dir) == 0o700
        for path in (
            Path(emergency["path"]),
            Path(automatic),
            Path(snapshot["path"]),
            Path(f"{snapshot['path']}.meta"),
        ):
            assert _mode(path) == 0o600

        db_path.chmod(0o644)
        result = preservation.restore_snapshot(snapshot["path"])
        assert result["status"] == "ok"
        assert _mode(db_path) == 0o600
    finally:
        database.close()


def test_preservation_rejects_symlinked_backup_directory(tmp_path: Path) -> None:
    db_path = tmp_path / "data.db"
    database = Database(db_path)
    target = tmp_path / "backup-target"
    target.mkdir(mode=0o700)
    (tmp_path / "backups").symlink_to(target, target_is_directory=True)
    try:
        with pytest.raises(StoragePermissionError, match="symbolic|符号链接"):
            DataPreservation(db=database)
    finally:
        database.close()


def test_existing_preservation_tree_is_migrated(tmp_path: Path) -> None:
    db_path = tmp_path / "data.db"
    database = Database(db_path)
    database.close()
    backup_dir = tmp_path / "backups"
    snapshot_dir = tmp_path / "snapshots"
    backup_dir.mkdir(mode=0o755)
    snapshot_dir.mkdir(mode=0o755)
    backup = backup_dir / "old.db"
    snapshot = snapshot_dir / "snapshot_old.db"
    metadata = snapshot_dir / "snapshot_old.db.meta"
    for path in (backup, snapshot, metadata):
        path.write_text("legacy")
        path.chmod(0o644)

    DataPreservation(db=None, db_path=str(db_path))

    assert _mode(backup_dir) == 0o700
    assert _mode(snapshot_dir) == 0o700
    for path in (backup, snapshot, metadata):
        assert _mode(path) == 0o600
