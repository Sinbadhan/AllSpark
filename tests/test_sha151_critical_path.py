"""SHA-151 Phase B1: critical-path branch coverage quick wins.

Targets the two critical-path modules closest to the 90% branch acceptance:
- knowledge_loader (import): was 91.7% branch (11/12) - cover the missing arc.
- reset_manager (reset): was 88.9% branch (32/36) - cover cooldown-passed +
  execute-reset-rejected + factory docker-failure paths.

These are the "quick wins" in the SHA-151 Gate+快赢 scope. SHA-151 stays open
until 75% total line / 90% critical-path branch is actually met.
"""
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from allspark.core.database import Database
from allspark.core.models import ResetLevel
from allspark.services.knowledge_loader import _load_yaml, get_tier_info
from allspark.services.reset_manager import ResetManager

# ─── knowledge_loader (import critical path) ────────────────────────────────


def test_load_yaml_returns_empty_when_file_missing(tmp_path: Path) -> None:
    # Covers the not-exists branch (line 23-25): file missing -> warn + [].
    result = _load_yaml(tmp_path / "nonexistent.yaml")
    assert result == []


def test_get_tier_info_returns_all_four_tiers() -> None:
    # Covers get_tier_info (line 96-102).
    info = get_tier_info()
    assert set(info.keys()) == {0, 1, 2, 3}
    for tier, data in info.items():
        assert {"name", "name_en", "file"} <= set(data.keys())


# ─── reset_manager (reset critical path) ─────────────────────────────────────


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture
def rm(db: Database) -> ResetManager:
    return ResetManager(db=db)


def test_cooldown_passed_allows_reset(rm: ResetManager) -> None:
    # Covers the false branch of `if elapsed < cooldown` (line 65->73):
    # a prior reset exists but the 24h cooldown has elapsed, so the reset
    # proceeds instead of being rejected.
    rm._last_reset_time = datetime.now() - timedelta(hours=25)
    result = rm.evaluate_reset(ResetLevel.ASSESSMENT)
    assert result["allowed"] is True
    assert result["level"] == 1


def test_execute_reset_rejected_without_force_during_cooldown(rm: ResetManager) -> None:
    # Covers the rejection path in execute_reset (line 104-108): a second
    # reset during cooldown without force is rejected.
    rm.execute_reset(ResetLevel.ASSESSMENT)  # arms the cooldown
    result = rm.execute_reset(ResetLevel.ASSESSMENT)  # no force -> rejected
    assert result["status"] == "rejected"
    assert result["reason"]  # warnings present


def test_factory_reset_handles_docker_manager_failure(db: Database) -> None:
    # Covers the except branch in _reset_factory (line 166-167): if the docker
    # manager raises during stop/reset, the factory reset still completes.
    failing_docker = MagicMock()
    failing_docker.stop_all.side_effect = RuntimeError("docker daemon down")
    rm = ResetManager(db=db, docker_manager=failing_docker)
    result = rm.execute_reset(ResetLevel.FACTORY, force=True)
    assert result["status"] == "ok"
    failing_docker.stop_all.assert_called_once()
    # stop_all raised before reset() could run; reset swallowed by the handler.
    failing_docker.reset.assert_not_called()
