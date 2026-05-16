import pytest

from allspark.data_preservation import DataPreservation
from allspark.database import Database


@pytest.fixture
def dp(tmp_path):
    db = Database(tmp_path / "test.db")
    preservation = DataPreservation(db=db)
    yield preservation
    db.close()


class TestDataPreservationIntegrity:
    def test_startup_check_new_db(self, dp):
        result = dp.startup_integrity_check()
        assert "integrity_ok" in result
        assert "warnings" in result
        assert "table_count" in result

    def test_startup_check_integrity_ok(self, dp):
        result = dp.startup_integrity_check()
        assert result["integrity_ok"] is True

    def test_startup_check_table_count(self, dp):
        result = dp.startup_integrity_check()
        assert result["table_count"] > 0

    def test_verify_integrity_main_db(self, dp):
        from pathlib import Path
        assert dp._verify_integrity(dp.db_path) is True


class TestDataPreservationSnapshot:
    def test_create_snapshot(self, dp):
        result = dp.create_snapshot(label="test")
        assert result["status"] == "ok"
        assert "path" in result
        assert "meta" in result
        assert result["meta"]["label"] == "test"

    def test_list_snapshots(self, dp):
        dp.create_snapshot(label="first")
        dp.create_snapshot(label="second")
        snapshots = dp.list_snapshots()
        assert len(snapshots) >= 2

    def test_restore_snapshot(self, dp):
        dp.create_snapshot(label="restore_test")
        snapshots = dp.list_snapshots()
        assert len(snapshots) > 0
        result = dp.restore_snapshot(snapshots[0]["path"])
        assert result["status"] == "ok"


class TestDataPreservationStatus:
    def test_get_status(self, dp):
        status = dp.get_status()
        assert "auto_save_running" in status
        assert "db_size_mb" in status
        assert "backup_count" in status
