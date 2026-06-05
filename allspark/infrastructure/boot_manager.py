import logging
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class BootReport:
    boot_time_ms: int
    stages: list
    total_stages: int
    failed_stages: int
    warnings: list


SYSTEMD_SERVICE = """\
[Unit]
Description=AllSpark - Offline AI Survival System
After=network.target
Wants=network-online.target

[Service]
Type=simple
User={user}
Group={group}
WorkingDirectory={workdir}
ExecStart={python} -m allspark --no-wizard --auto-start
ExecStop={python} -m allspark --shutdown
Restart=on-failure
RestartSec=10
StartLimitIntervalSec=60
StartLimitBurst=3

WatchdogSec=120
NotifyAccess=all

StandardOutput=journal
StandardError=journal
SyslogIdentifier=allspark

Environment=PYTHONUNBUFFERED=1
Environment=ALLSPARK_HOME={workdir}

[Install]
WantedBy=multi-user.target
"""

WATCHDOG_SCRIPT = """\
#!/usr/bin/env python3
import logging
import sys
import time
import sqlite3
from pathlib import Path

DB_PATH = DEFAULT_DB_PATH
CHECK_INTERVAL = 30
MAX_HEARTBEAT_AGE = 120

def check_health():
    try:
        if not DB_PATH.exists():
            return False, "Database not found"
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT value FROM operating_state WHERE key='last_heartbeat'"
            ).fetchone()
            if not row:
                return True, "No heartbeat record (first run?)"
            return True, "OK"
        finally:
            conn.close()
    except Exception as e:
        return False, str(e)

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logger = logging.getLogger("allspark.watchdog")
    while True:
        healthy, msg = check_health()
        if not healthy:
            logger.error("AllSpark health check FAILED: %s", msg)
            sys.exit(1)
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
"""


class BootManager:
    def __init__(self, db=None):
        self.db = db
        self._boot_start = 0.0
        self._stages: list[dict] = []
        self._initialized = False

    def start_boot(self) -> float:
        self._boot_start = time.monotonic()
        self._stages = []
        return self._boot_start

    def record_stage(self, name: str, success: bool = True,
                     message: str = "", duration_ms: int = 0):
        self._stages.append({
            "name": name,
            "success": success,
            "message": message,
            "duration_ms": duration_ms,
            "timestamp": datetime.now().isoformat(),
        })

    def time_stage(self, name: str):
        return _StageTimer(self, name)

    def finish_boot(self) -> BootReport:
        total_ms = int((time.monotonic() - self._boot_start) * 1000)
        failed = [s for s in self._stages if not s["success"]]
        warnings = [s["message"] for s in self._stages if s["message"] and s["success"]]

        report = BootReport(
            boot_time_ms=total_ms,
            stages=self._stages,
            total_stages=len(self._stages),
            failed_stages=len(failed),
            warnings=warnings,
        )

        self._initialized = True

        if self.db:
            try:
                self.db.conn.execute(
                    "INSERT OR REPLACE INTO operating_state VALUES (?, ?)",
                    ("last_boot_time", datetime.now().isoformat())
                )
                self.db.conn.execute(
                    "INSERT OR REPLACE INTO operating_state VALUES (?, ?)",
                    ("boot_duration_ms", str(total_ms))
                )
                self.db.conn.commit()
            except Exception:
                pass

        return report

    def update_heartbeat(self):
        if self.db:
            try:
                self.db.conn.execute(
                    "INSERT OR REPLACE INTO operating_state VALUES (?, ?)",
                    ("last_heartbeat", datetime.now().isoformat())
                )
                self.db.conn.commit()
            except Exception:
                pass

    def get_boot_report(self) -> dict:
        return {
            "initialized": self._initialized,
            "stages": self._stages,
            "total_stages": len(self._stages),
        }

    @staticmethod
    def generate_systemd_service(output_path: Optional[str] = None) -> str:
        content = SYSTEMD_SERVICE.format(
            user=os.environ.get("USER", "pi"),
            group=os.environ.get("USER", "pi"),
            workdir=str(Path.cwd()),
            python=sys.executable,
        )

        if output_path:
            Path(output_path).write_text(content)
        return content

    @staticmethod
    def install_systemd_service() -> dict:
        if platform.system() != "Linux":
            return {"status": "error", "message": "systemd only available on Linux"}

        service_dir = Path("/etc/systemd/system")
        service_file = service_dir / "allspark.service"

        if not os.access(str(service_dir), os.W_OK):
            return {"status": "error", "message": "Need sudo/root to install systemd service"}

        try:
            content = BootManager.generate_systemd_service()
            service_file.write_text(content)

            subprocess.run(["systemctl", "daemon-reload"], check=True, timeout=10)
            subprocess.run(["systemctl", "enable", "allspark.service"], check=True, timeout=10)

            return {"status": "ok", "service_file": str(service_file)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @staticmethod
    def generate_watchdog_script(output_path: Optional[str] = None) -> str:
        if output_path:
            Path(output_path).write_text(WATCHDOG_SCRIPT)
            os.chmod(output_path, 0o755)
        return WATCHDOG_SCRIPT

    @staticmethod
    def get_service_status() -> dict:
        if platform.system() != "Linux":
            return {"status": "unavailable", "message": "Not running on Linux"}

        try:
            result = subprocess.run(
                ["systemctl", "is-active", "allspark.service"],
                capture_output=True, text=True, timeout=5
            )
            active = result.stdout.strip()

            result2 = subprocess.run(
                ["systemctl", "is-enabled", "allspark.service"],
                capture_output=True, text=True, timeout=5
            )
            enabled = result2.stdout.strip()

            return {
                "active": active,
                "enabled": enabled,
                "installed": active != "unknown" or enabled != "unknown",
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_status(self) -> dict:
        return {
            "initialized": self._initialized,
            "platform": platform.system(),
            "python": sys.version.split()[0],
            "stages_completed": len(self._stages),
            "boot_time_ms": sum(s.get("duration_ms", 0) for s in self._stages),
        }


class _StageTimer:
    def __init__(self, boot_mgr: BootManager, name: str):
        self._mgr = boot_mgr
        self._name = name
        self._start = 0.0

    def __enter__(self):
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = int((time.monotonic() - self._start) * 1000)
        success = exc_type is None
        message = str(exc_val) if exc_val else ""
        self._mgr.record_stage(self._name, success, message, duration)
        return False
