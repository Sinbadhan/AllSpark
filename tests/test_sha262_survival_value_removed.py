"""SHA-262: person-value ranking is removed without identity disclosure."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from allspark.commands.governance import GovernanceCommand
from allspark.container import ServiceContainer
from allspark.core.database import Database
from allspark.core.i18n import get_language, set_language, t
from allspark.core.models import GovernanceRole
from allspark.services.governance import PERMISSIONS, GovernanceEngine
from tests.test_web_ui_v11 import TempDb, _client


@pytest.fixture(autouse=True)
def restore_language():
    original = get_language()
    yield
    set_language(original, persist=False)


def _assert_uniform_removed_payload(payload: dict) -> None:
    assert payload["status"] == "unsupported"
    assert payload["release_status"] == "removed"
    assert payload["reason"] == "person_value_ranking_removed"
    serialized = str(payload).lower()
    for forbidden in (
        "member_id",
        "member_name",
        "dimensions",
        "composite_value",
        "health_status",
        "psychological_stability",
    ):
        assert forbidden not in serialized


def test_permissions_do_not_include_person_value_operations() -> None:
    for permissions in PERMISSIONS.values():
        assert "trigger_survival_value" not in permissions
        assert "view_survival_value" not in permissions


def test_legacy_service_call_is_uniform_for_known_and_unknown_members(tmp_path) -> None:
    db = Database(tmp_path / "governance.db")
    try:
        service = GovernanceEngine(db=db)
        member = service.add_member(
            "Alice",
            role=GovernanceRole.SPECIALIST.value,
            domains=["medical"],
            skills=["surgery"],
            health_status="excellent",
        )
        service.update_contribution(member.id, 99.0)

        known = service.calculate_survival_value(member.id)
        unknown = service.calculate_survival_value("member-does-not-exist")
        empty = service.calculate_survival_value("")

        assert known == unknown == empty
        _assert_uniform_removed_payload(known)
    finally:
        db.close()


@pytest.mark.parametrize("language", ["en", "zh"])
def test_legacy_api_returns_uniform_410_without_member_enumeration(language) -> None:
    with TempDb() as path:
        client = _client(path)
        set_language(language, persist=False)
        no_id = client.get("/api/governance/survival-value")
        known_shape = client.get(
            "/api/governance/survival-value", params={"member_id": "member-known"}
        )
        unknown = client.get(
            "/api/governance/survival-value", params={"member_id": "member-unknown"}
        )

    assert no_id.status_code == known_shape.status_code == unknown.status_code == 410
    assert no_id.json() == known_shape.json() == unknown.json()
    _assert_uniform_removed_payload(no_id.json())
    assert no_id.json()["error"] == t("survival_value_removed")
    assert no_id.json()["detail"]
    assert no_id.json()["next_action"]


def test_legacy_api_is_not_advertised_in_public_schema() -> None:
    with TempDb() as path:
        schema = _client(path).get("/openapi.json").json()

    assert "/api/governance/survival-value" not in schema["paths"]


@pytest.mark.parametrize(
    ("language", "command"), [("en", "value"), ("zh", "价值")]
)
def test_legacy_cli_call_explains_removal_before_governance_lookup(
    tmp_path, language, command
) -> None:
    set_language(language, persist=False)
    db = Database(tmp_path / f"cli-{language}.db")
    container = ServiceContainer(db=db)
    command_handler = GovernanceCommand(container)
    command_handler.console = MagicMock()
    try:
        command_handler.execute([command, "member-secret"])
        rendered = " ".join(
            str(call.args[0]) for call in command_handler.console.print.call_args_list
        )
        assert t("survival_value_removed") in rendered
        assert "member-secret" not in rendered
        assert container.get("governance") is None
    finally:
        db.close()


def test_removed_command_is_absent_from_help_and_usage() -> None:
    for language in ("en", "zh"):
        set_language(language, persist=False)
        assert " value " not in f" {t('governance_usage').lower()} "
        assert " value " not in f" {t('community_usage_detail').lower()} "

    rule_engine = Path("allspark/services/rule_engine.py").read_text(encoding="utf-8")
    command = Path("allspark/commands/governance.py").read_text(encoding="utf-8")
    assert "help_community_value" not in rule_engine
    assert "calculate_survival_value(mid)" not in command


def test_no_derived_person_value_was_persisted_or_needs_migration(tmp_path) -> None:
    db = Database(tmp_path / "schema.db")
    try:
        schema = "\n".join(
            row["sql"] or ""
            for row in db.conn.execute(
                "SELECT sql FROM sqlite_master WHERE type IN ('table', 'index')"
            ).fetchall()
        ).lower()
    finally:
        db.close()

    assert "survival_value" not in schema
    assert "composite_value" not in schema


def test_public_docs_state_removal_and_safer_replacement() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_zh = Path("README_CN.md").read_text(encoding="utf-8")
    prd = Path("PRD.md").read_text(encoding="utf-8")

    assert "Person-value ranking (Removed)" in readme
    assert "人员价值排序（已移除）" in readme_zh
    assert "人员价值排序（Removed）" in prd
    assert "任务需求、已声明技能和覆盖缺口" in prd
    assert "健康、心理状态、贡献或其他个人属性" in readme_zh
