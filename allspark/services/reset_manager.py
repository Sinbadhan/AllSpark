import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from allspark.core.i18n import t
from allspark.core.models import OperatingMode, ResetLevel

logger = logging.getLogger(__name__)

_RESET_COOLDOWN_HOURS = 24


@dataclass(frozen=True)
class ResetPolicy:
    description_key: str
    affected_keys: tuple[str, ...]
    clear_tables: frozenset[str] = frozenset()
    clear_all_application_tables: bool = False


# Executable source of truth for reset scope. CLI evaluation and the Web UI
# both render the description_key from this matrix; reset methods consume the
# same table sets. Partial key/value-table preservation is handled explicitly
# in the corresponding reset method below.
RESET_POLICIES = {
    ResetLevel.ASSESSMENT: ResetPolicy(
        description_key="reset_l1_description",
        affected_keys=(
            "reset_affected_operating_state",
            "reset_affected_survivor_state",
            "reset_affected_hardware_profile",
        ),
    ),
    ResetLevel.ARCHIVE: ResetPolicy(
        description_key="reset_l2_description",
        affected_keys=(
            "reset_affected_operating_state",
            "reset_affected_survivor_state",
            "reset_affected_resources",
            "reset_affected_tasks",
            "reset_affected_goals",
            "reset_affected_milestones",
        ),
        clear_tables=frozenset(
            {
                "resources",
                "tasks",
                "experience_log",
                "map_pois",
                "community_members",
                "conflicts",
                "trade_offers",
                "goals",
                "milestones",
                "timeline_events",
                "diary_entries",
                "diary_fts",
                "spark_location",
                "psych_state",
                "action_plans",
            }
        ),
    ),
    ResetLevel.FACTORY: ResetPolicy(
        description_key="reset_l3_description",
        affected_keys=("reset_affected_all_data",),
        clear_all_application_tables=True,
    ),
}


def get_reset_descriptions() -> dict[int, str]:
    return {
        level.value: t(policy.description_key)
        for level, policy in RESET_POLICIES.items()
    }

# Operating-state keys that must survive an L1 (assessment) or L2 (archive)
# reset so the next launch does not look like a fresh install.
_PROTECTED_OPERATING_STATE_KEYS = {
    "initialized",
    "language",
    "deploy_mode",
    "timeline_start_at",
    "last_mode_change",
}

# Survivor-state keys that survive L1 so language / name persist.
_PROTECTED_SURVIVOR_STATE_KEYS = {
    "language",
    "name",
}

# Hardware-profile keys that survive L1 so detected hardware tier and the
# GPS track history are not wiped by an "assessment" reset.
_PROTECTED_HARDWARE_PROFILE_PREFIXES = (
    "track-",
    "last_gps_position",
    "manual_pressure",
)


class ResetManager:
    def __init__(self, db, data_preservation=None, resource_mgr=None, docker_manager=None):
        self.db = db
        self.data_preservation = data_preservation
        self.resource_mgr = resource_mgr
        self.docker_manager = docker_manager
        self._last_reset_time = self._load_last_reset_time()

    def evaluate_reset(self, level: ResetLevel) -> dict:
        result: dict[str, Any] = {
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

        policy = RESET_POLICIES[level]
        result["affected_data"] = [t(key) for key in policy.affected_keys]
        result["description"] = t(policy.description_key)
        if level == ResetLevel.FACTORY:
            result["warnings"].append(t("reset_l3_warning_irreversible"))

        return result

    def execute_reset(
        self,
        level: ResetLevel,
        force: bool = False,
        performed_by: str = "system",
    ) -> dict:
        evaluation = self.evaluate_reset(level)
        if not evaluation["allowed"] and not force:
            reason = self._format_reasons(evaluation["warnings"])
            self._save_audit_log(
                level=level,
                status="rejected",
                reason=reason,
                performed_by=performed_by,
            )
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

        try:
            if level == ResetLevel.ASSESSMENT:
                self._reset_assessment()
            elif level == ResetLevel.ARCHIVE:
                self._reset_archive()
            elif level == ResetLevel.FACTORY:
                self._reset_factory()
        except Exception as exc:
            self.db.conn.rollback()
            self._save_audit_log(
                level=level,
                status="failed",
                reason=str(exc),
                performed_by=performed_by,
                backup_id=self._backup_id(backup_result),
            )
            raise

        completed_at = datetime.now()
        reason_parts = ["force=true"] if force else []
        if force:
            reason_parts.extend(evaluation["warnings"])
        try:
            self._save_audit_log(
                level=level,
                status="accepted",
                reason=self._format_reasons(reason_parts),
                performed_by=performed_by,
                backup_id=self._backup_id(backup_result),
                performed_at=completed_at,
            )
        except Exception:
            self.db.conn.rollback()
            raise
        self._last_reset_time = completed_at

        return {
            "status": "ok",
            "level": level.name,
            "backup": backup_result,
            "timestamp": completed_at.isoformat(),
        }

    def _reset_assessment(self):
        protected_op = self._snapshot_protected(
            "operating_state", _PROTECTED_OPERATING_STATE_KEYS
        )
        protected_sv = self._snapshot_protected(
            "survivor_state", _PROTECTED_SURVIVOR_STATE_KEYS
        )
        protected_hw = self._snapshot_hardware_protected()

        self.db.conn.execute("DELETE FROM operating_state WHERE 1")
        self.db.conn.execute("DELETE FROM survivor_state WHERE 1")
        self.db.conn.execute("DELETE FROM hardware_profile WHERE 1")
        self._restore_kv("operating_state", protected_op)
        self._restore_kv("survivor_state", protected_sv)
        self._restore_kv("hardware_profile", protected_hw)

    def _reset_archive(self):
        protected_op = self._snapshot_protected(
            "operating_state", _PROTECTED_OPERATING_STATE_KEYS
        )
        protected_sv = self._snapshot_protected("survivor_state", {"language"})
        try:
            self.db.conn.execute("DELETE FROM operating_state")
            self.db.conn.execute("DELETE FROM survivor_state")
            self._clear_tables(RESET_POLICIES[ResetLevel.ARCHIVE].clear_tables)
            self._restore_kv("operating_state", protected_op)
            self._restore_kv("survivor_state", protected_sv)
        except Exception:
            self.db.conn.rollback()
            raise

    def _reset_factory(self):
        if self.docker_manager:
            try:
                self.docker_manager.stop_all()
                self.docker_manager.reset()
            except Exception as e:
                logger.warning(
                    "Failed to stop/reset docker manager during factory reset: %s", e
                )

        language = self._snapshot_protected("operating_state", {"language"})
        if not language:
            language = self._snapshot_protected("survivor_state", {"language"})
        try:
            self._clear_tables(self.db.get_application_tables())
            self._restore_kv("operating_state", language)
        except Exception:
            self.db.conn.rollback()
            raise

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

    def _load_last_reset_time(self) -> datetime | None:
        getter = getattr(self.db, "get_latest_accepted_reset", None)
        if getter is None:
            return None
        row = getter()
        if not row or not row.get("performed_at"):
            return None
        try:
            return datetime.fromisoformat(row["performed_at"])
        except (TypeError, ValueError):
            logger.warning("Ignoring invalid reset_log timestamp: %r", row["performed_at"])
            return None

    def _save_audit_log(
        self,
        *,
        level: ResetLevel,
        status: str,
        reason: str,
        performed_by: str,
        backup_id: str = "",
        performed_at: datetime | None = None,
    ) -> None:
        self.db.save_reset_log(
            uuid.uuid4().hex,
            level.value,
            reason=reason,
            backup_id=backup_id,
            performed_by=performed_by,
            status=status,
            performed_at=(performed_at or datetime.now()).isoformat(),
        )

    @staticmethod
    def _backup_id(backup_result: dict) -> str:
        return str(backup_result.get("path") or backup_result.get("id") or "")

    @staticmethod
    def _format_reasons(reasons: list[Any]) -> str:
        return " | ".join(str(reason) for reason in reasons if reason)

    # ─── Protected state helpers ────────────────────────────────────────

    def _snapshot_protected(self, table: str, keys) -> dict:
        rows = self.db.conn.execute(f"SELECT key, value FROM {table}").fetchall()
        return {row["key"]: row["value"] for row in rows if row["key"] in keys}

    def _snapshot_hardware_protected(self) -> dict:
        rows = self.db.conn.execute("SELECT key, value FROM hardware_profile").fetchall()
        result = {}
        for row in rows:
            key = row["key"]
            if any(key.startswith(prefix) for prefix in _PROTECTED_HARDWARE_PROFILE_PREFIXES):
                result[key] = row["value"]
        return result

    def _restore_kv(self, table: str, data: dict):
        for key, value in data.items():
            self.db.conn.execute(
                f"INSERT OR REPLACE INTO {table} VALUES (?,?)", (key, value)
            )

    def _clear_tables(self, tables) -> None:
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            self.db.conn.execute(f"DELETE FROM {quoted}")
