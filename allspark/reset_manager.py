import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from allspark.i18n import t
from allspark.models import ResetLevel, OperatingMode


_RESET_COOLDOWN_HOURS = 24


class ResetManager:
    def __init__(self, db, data_preservation=None, resource_mgr=None, docker_manager=None):
        self.db = db
        self.data_preservation = data_preservation
        self.resource_mgr = resource_mgr
        self.docker_manager = docker_manager
        self._last_reset_time = None

    def evaluate_reset(self, level: ResetLevel) -> dict:
        result = {
            "level": level.value,
            "level_name": level.name,
            "allowed": True,
            "warnings": [],
            "affected_data": [],
            "backup_recommended": True,
        }

        state = self.db.get_operating_state()
        mode = OperatingMode(state.mode)

        if mode == OperatingMode.HIBERNATION:
            result["allowed"] = False
            result["warnings"].append(t("reset_forbidden_hibernation"))
            return result

        if self._last_reset_time:
            elapsed = datetime.now() - self._last_reset_time
            if elapsed < timedelta(hours=_RESET_COOLDOWN_HOURS):
                remaining = timedelta(hours=_RESET_COOLDOWN_HOURS) - elapsed
                result["allowed"] = False
                result["warnings"].append(
                    t("reset_cooldown_active", hours=int(remaining.total_seconds() / 3600))
                )
                return result

        if level == ResetLevel.ASSESSMENT:
            result["affected_data"] = [
                t("reset_affected_operating_state"),
                t("reset_affected_survivor_state"),
                t("reset_affected_hardware_profile"),
            ]
            result["description"] = t("reset_l1_description")

        elif level == ResetLevel.ARCHIVE:
            result["affected_data"] = [
                t("reset_affected_operating_state"),
                t("reset_affected_survivor_state"),
                t("reset_affected_hardware_profile"),
                t("reset_affected_resources"),
                t("reset_affected_tasks"),
                t("reset_affected_goals"),
                t("reset_affected_milestones"),
            ]
            result["description"] = t("reset_l2_description")

        elif level == ResetLevel.FACTORY:
            result["affected_data"] = [
                t("reset_affected_all_data"),
            ]
            result["description"] = t("reset_l3_description")
            result["warnings"].append(t("reset_l3_warning_irreversible"))

        return result

    def execute_reset(self, level: ResetLevel, force: bool = False) -> dict:
        evaluation = self.evaluate_reset(level)
        if not evaluation["allowed"] and not force:
            return {
                "status": "rejected",
                "reason": evaluation["warnings"],
            }

        if self.data_preservation:
            backup_result = self.data_preservation.create_snapshot(
                label=f"pre-reset-L{level.value}"
            )
        else:
            backup_result = {"status": "skipped"}

        if level == ResetLevel.ASSESSMENT:
            self._reset_assessment()
        elif level == ResetLevel.ARCHIVE:
            self._reset_archive()
        elif level == ResetLevel.FACTORY:
            self._reset_factory()

        self._last_reset_time = datetime.now()

        return {
            "status": "ok",
            "level": level.name,
            "backup": backup_result,
            "timestamp": datetime.now().isoformat(),
        }

    def _reset_assessment(self):
        self.db.conn.execute("DELETE FROM operating_state WHERE 1")
        self.db.conn.execute("DELETE FROM survivor_state WHERE 1")
        self.db.conn.execute("DELETE FROM hardware_profile WHERE 1")
        self.db.conn.commit()

    def _reset_archive(self):
        self._reset_assessment()
        self.db.conn.execute("DELETE FROM resources WHERE 1")
        self.db.conn.execute("DELETE FROM tasks WHERE 1")
        self.db.conn.execute("DELETE FROM goals WHERE 1")
        self.db.conn.execute("DELETE FROM milestones WHERE 1")
        self.db.conn.execute("DELETE FROM experience_log WHERE 1")
        self.db.conn.execute("DELETE FROM map_pois WHERE 1")
        self.db.conn.commit()

    def _reset_factory(self):
        if self.docker_manager:
            try:
                self.docker_manager.stop_all()
                self.docker_manager.reset()
            except Exception:
                pass

        tables = [
            "resources", "tasks", "knowledge", "knowledge_fts",
            "experience_log", "map_pois", "operating_state",
            "survivor_state", "hardware_profile",
            "community_members", "conflicts", "trade_offers",
            "goals", "milestones", "timeline_events",
            "diary_entries", "diary_fts", "reset_log",
            "spark_location", "psych_state",
        ]
        for table in tables:
            try:
                self.db.conn.execute(f"DELETE FROM {table}")
            except Exception:
                pass
        self.db.conn.commit()
        self.db.mark_uninitialized()

    def get_reset_status(self) -> dict:
        return {
            "last_reset": self._last_reset_time.isoformat() if self._last_reset_time else None,
            "cooldown_hours": _RESET_COOLDOWN_HOURS,
            "can_reset": self._can_reset_now(),
        }

    def _can_reset_now(self) -> bool:
        if self._last_reset_time is None:
            return True
        elapsed = datetime.now() - self._last_reset_time
        return elapsed >= timedelta(hours=_RESET_COOLDOWN_HOURS)
