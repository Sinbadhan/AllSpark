from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from allspark.bootstrap import ApplicationBootstrap
from allspark.commands.governance import GovernanceCommand
from allspark.container import ServiceContainer
from allspark.core.database import Database
from allspark.core.i18n import set_language
from allspark.infrastructure.hardware import (
    FeatureFlags,
    HardwareTier,
    compute_feature_flags,
)
from allspark.infrastructure.module_loader import (
    EXPERIMENTAL_MODULES,
    PRODUCT_DISABLED_MODULES,
    ModuleRegistry,
)
from allspark.services.governance import GovernanceEngine
from tests.test_web_ui_v11 import TempDb, _client


@pytest.mark.parametrize("tier", list(HardwareTier))
def test_hardware_never_claims_governance_is_enabled(tier: HardwareTier) -> None:
    assert compute_feature_flags(tier).governance is False


def test_registry_hard_disables_governance_even_with_old_true_flag() -> None:
    registry = ModuleRegistry(FeatureFlags(governance=True))
    status = next(
        item for item in registry.format_status_dict() if item["name"] == "governance"
    )
    assert "governance" in PRODUCT_DISABLED_MODULES
    assert "governance" in EXPERIMENTAL_MODULES
    assert registry.should_load("governance") is False
    assert registry.enable("governance") is False
    assert registry.flags.governance is False
    assert status["hw_supported"] is False
    assert status["status"] == "disabled"
    assert status["experimental"] is True


def test_legacy_saved_governance_flag_cannot_reenable_module(tmp_path) -> None:
    db = Database(tmp_path / "legacy-governance.db")
    try:
        db.save_hardware_profile(
            "feature_flags", json.dumps({"governance": True, "web_ui": True})
        )
        db.save_hardware_profile("disabled_modules", "[]")
        registry = ModuleRegistry.load_from_db(db)
        assert registry is not None
        assert registry.flags.governance is False
        assert registry.should_load("governance") is False
    finally:
        db.close()


def test_bootstrap_does_not_publish_governance_service_with_true_flag(tmp_path) -> None:
    db = Database(tmp_path / "bootstrap-governance.db")
    bootstrap = ApplicationBootstrap(db, FeatureFlags(governance=True))
    try:
        container = bootstrap.bootstrap()
        assert container.get("governance") is None
        assert bootstrap.registry.is_loaded("governance") is False
    finally:
        bootstrap.shutdown()
        db.close()


def test_cli_does_not_use_even_injected_governance_service(tmp_path) -> None:
    set_language("en")
    db = Database(tmp_path / "cli-governance.db")
    container = ServiceContainer(db=db)
    service = MagicMock(spec=GovernanceEngine)
    container.register("governance", service)
    command = GovernanceCommand(container)
    command.console = MagicMock()
    try:
        command.execute(["add", "alice", "commander"])
        service.add_member.assert_not_called()
        rendered = str(command.console.print.call_args.args[0])
        assert "unavailable in the v1 Stable" in rendered
    finally:
        db.close()


def test_repository_shows_boundary_without_governance_controls() -> None:
    with TempDb() as path:
        html = _client(path).get("/repository").text
    assert 'data-repo-action="add-member"' not in html
    assert 'id="member-name"' not in html
    assert "Governance is unavailable in the v1 Stable boundary." in html
    assert "Governance status · Experimental" in html


def test_governance_cannot_be_reenabled_through_modules_api() -> None:
    with TempDb() as path:
        client = _client(path)
        response = client.post("/api/modules/governance/enable")
        modules = client.get("/api/modules").json()

    governance = next(item for item in modules if item["name"] == "governance")
    assert response.status_code != 200
    assert governance["status"] == "disabled"
    assert governance["hw_supported"] is False
    assert governance["experimental"] is True
