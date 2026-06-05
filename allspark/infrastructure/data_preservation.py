import hashlib
import json
import logging
import shutil
import signal
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from allspark.core.config import DEFAULT_DB_DIR

logger = logging.getLogger(__name__)


class DataPreservation:
    def __init__(self, db=None, db_path: Optional[str] = None):
        self.db = db
        self.db_path = Path(db_path) if db_path else (
            Path(db.db_path) if db and hasattr(db, 'db_path') else (DEFAULT_DB_DIR / "data.db")
        )
        self.backup_dir = self.db_path.parent / "backups"
        self.snapshot_dir = self.db_path.parent / "snapshots"
        self._auto_save_interval = 300
        self._running = False
        self._save_thread: Optional[threading.Thread] = None
        self._last_save_time: Optional[str] = None
        self._save_count = 0
        self._signal_handlers_installed = False

    def start_auto_save(self, interval_seconds: int = 300) -> dict:
        if self._running:
            return {"status": "already_running"}

        self._auto_save_interval = interval_seconds
        self._running = True
        self._install_signal_handlers()

        self._save_thread = threading.Thread(
            target=self._auto_save_loop, daemon=True
        )
        self._save_thread.start()

        logger.info(f"Auto-save started (interval={interval_seconds}s)")
        return {"status": "started", "interval_s": interval_seconds}

    def stop_auto_save(self) -> dict:
        self._running = False
        if self._save_thread:
            self._save_thread.join(timeout=10)
        self.emergency_save(reason="shutdown")
        return {"status": "stopped", "total_saves": self._save_count}

    def _auto_save_loop(self):
        while self._running:
            time.sleep(self._auto_save_interval)
            if self._running:
                try:
                    self._periodic_save()
                except Exception as e:
                    logger.error(f"Auto-save error: {e}")

    def _periodic_save(self):
        self._create_backup()
        self._save_count += 1
        self._last_save_time = datetime.now().isoformat()
        logger.debug(f"Auto-save #{self._save_count} completed")

    def emergency_save(self, reason: str = "unknown") -> dict:
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"emergency_{reason}_{timestamp}.db"
            backup_path = self.backup_dir / backup_name

            if self.db_path.exists():
                if self.db:
                    try:
                        self.db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                        self.db.conn.commit()
                    except Exception:
                        pass

                shutil.copy2(str(self.db_path), str(backup_path))
                integrity = self._verify_integrity(backup_path)
                logger.warning(f"Emergency save: {backup_name} integrity={integrity}")
                return {"status": "ok", "path": str(backup_path), "integrity": integrity, "reason": reason}
            return {"status": "no_db_file"}

        except Exception as e:
            logger.error(f"Emergency save failed: {e}")
            return {"status": "error", "message": str(e)}

    def _create_backup(self) -> Optional[str]:
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.backup_dir / f"auto_{timestamp}.db"

            if self.db_path.exists():
                if self.db:
                    try:
                        self.db.conn.commit()
                    except Exception:
                        pass
                shutil.copy2(str(self.db_path), str(backup_path))
                self._cleanup_old_backups()
                return str(backup_path)
        except Exception as e:
            logger.warning(f"Backup creation failed: {e}")
        return None

    def _cleanup_old_backups(self, max_backups: int = 24):
        try:
            backups = sorted(
                self.backup_dir.glob("auto_*.db"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for old in backups[max_backups:]:
                old.unlink()
        except Exception:
            pass

    def create_snapshot(self, label: str = "") -> dict:
        try:
            self.snapshot_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            label_part = f"_{label}" if label else ""
            snap_name = f"snapshot_{timestamp}{label_part}.db"
            snap_path = self.snapshot_dir / snap_name

            if self.db_path.exists():
                if self.db:
                    try:
                        self.db.conn.commit()
                    except Exception:
                        pass
                shutil.copy2(str(self.db_path), str(snap_path))
                meta = {
                    "label": label,
                    "created": datetime.now().isoformat(),
                    "db_size_mb": round(snap_path.stat().st_size / (1024 * 1024), 2),
                    "checksum": self._checksum(snap_path),
                }
                meta_path = self.snapshot_dir / f"{snap_name}.meta"
                with open(meta_path, "w") as f:
                    json.dump(meta, f, indent=2, ensure_ascii=False)
                return {"status": "ok", "path": str(snap_path), "meta": meta}
            return {"status": "no_db_file"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def list_snapshots(self) -> list[dict]:
        if not self.snapshot_dir.exists():
            return []
        snapshots = []
        for meta_path in sorted(self.snapshot_dir.glob("snapshot_*.db.meta")):
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
                meta["path"] = str(meta_path.with_suffix(""))
                snapshots.append(meta)
            except Exception:
                pass
        return snapshots

    def restore_snapshot(self, label_or_path: str) -> dict:
        try:
            snap_path = Path(label_or_path)
            if not snap_path.exists():
                candidates = list(self.snapshot_dir.glob(f"*{label_or_path}*.db"))
                if not candidates:
                    return {"status": "error", "message": "Snapshot not found"}
                snap_path = candidates[0]

            integrity = self._verify_integrity(snap_path)
            if not integrity:
                return {"status": "error", "message": "Snapshot integrity check failed"}

            if self.db:
                try:
                    self.db.conn.close()
                except Exception:
                    pass

            shutil.copy2(str(snap_path), str(self.db_path))

            return {"status": "ok", "restored_from": str(snap_path), "integrity": integrity}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _verify_integrity(self, db_path: Path) -> bool:
        try:
            if self.db and Path(str(self.db_path)) == db_path.resolve():
                result = self.db.conn.execute("PRAGMA integrity_check").fetchone()
            else:
                conn = sqlite3.connect(str(db_path))
                result = conn.execute("PRAGMA integrity_check").fetchone()
                conn.close()
            return result[0] == "ok"
        except Exception:
            return False

    def _checksum(self, path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()[:16]

    def _install_signal_handlers(self):
        if self._signal_handlers_installed:
            return
        self._signal_handlers_installed = True

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, self._signal_handler)
            except (OSError, ValueError):
                pass

        try:
            signal.signal(signal.SIGHUP, self._sighup_handler)
        except (OSError, ValueError, AttributeError):
            pass

    def _signal_handler(self, signum, frame):
        sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        logger.warning(f"Received signal {sig_name}, performing emergency save...")
        self.emergency_save(reason=f"signal_{sig_name}")

    def _sighup_handler(self, signum, frame):
        logger.info("Received SIGHUP, performing periodic save...")
        self._periodic_save()

    def get_status(self) -> dict:
        db_size = 0
        if self.db_path.exists():
            db_size = self.db_path.stat().st_size

        backup_count = 0
        if self.backup_dir.exists():
            backup_count = len(list(self.backup_dir.glob("*.db")))

        snapshot_count = 0
        if self.snapshot_dir.exists():
            snapshot_count = len(list(self.snapshot_dir.glob("snapshot_*.db")))

        return {
            "auto_save_running": self._running,
            "auto_save_interval_s": self._auto_save_interval,
            "last_save_time": self._last_save_time,
            "total_saves": self._save_count,
            "db_size_mb": round(db_size / (1024 * 1024), 2),
            "backup_count": backup_count,
            "snapshot_count": snapshot_count,
            "db_path": str(self.db_path),
        }

    def startup_integrity_check(self) -> dict:
        result = {
            "db_file_exists": self.db_path.exists(),
            "integrity_ok": False,
            "table_count": 0,
            "warnings": [],
        }

        if not self.db_path.exists():
            result["warnings"].append("Database file does not exist - will be created on first use")
            return result

        if self.db:
            result["integrity_ok"] = self.db.check_integrity()
        else:
            result["integrity_ok"] = self._verify_integrity(self.db_path)

        if not result["integrity_ok"]:
            result["warnings"].append("Database integrity check failed - consider restoring from backup")
            return result

        try:
            conn = self.db.conn if self.db else sqlite3.connect(str(self.db_path))
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            result["table_count"] = len(tables)

            expected_tables = {
                "resources", "tasks", "knowledge", "knowledge_fts",
                "experience_log", "map_pois", "operating_state",
                "survivor_state", "hardware_profile",
                "community_members", "conflicts", "trade_offers",
            }
            existing = {t[0] if isinstance(t, (list, tuple)) else t["name"] for t in tables}
            missing = expected_tables - existing
            if missing:
                result["warnings"].append(f"Missing tables: {', '.join(sorted(missing))}")

            if not self.db:
                conn.close()
        except Exception as e:
            result["warnings"].append(f"Schema check error: {e}")

        return result
