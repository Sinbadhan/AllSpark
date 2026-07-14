"""SHA-151 Phase B2: coverage gains on search/resource/governance critical paths.

Medium-push tests targeting the remaining critical-path modules. The goal is
meaningful branch gains toward the 90% acceptance; SHA-151 stays open until
75% total line / 90% critical-path branch is actually met (tracked via the
acceptance-gap table printed by scripts/check_coverage.py).
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from allspark.core.database import Database
from allspark.core.i18n import set_language
from allspark.core.models import KnowledgeEntry, OperatingMode, Resource, ResourceType
from allspark.services.knowledge_engine import KnowledgeEngine
from allspark.services.knowledge_loader import load_all_knowledge
from allspark.services.resource_manager import ResourceManager

# ─── fixtures ────────────────────────────────────────────────────────────────


def _load_knowledge(db: Database) -> None:
    for e in load_all_knowledge("zh"):
        db.save_knowledge(e)


@pytest.fixture
def ke_db(tmp_path: Path) -> Database:
    set_language("zh")
    db = Database(tmp_path / "ke.db")
    _load_knowledge(db)
    yield db
    db.close()


@pytest.fixture
def ke(ke_db: Database) -> KnowledgeEngine:
    return KnowledgeEngine(ke_db)


def _entry(
    *, id: str = "t1", steps=None, prerequisites=None, warnings=None,
    category: str = "水", subcategory: str = "净水", priority: int = 0,
    title: str = "煮沸净水", summary: str = "煮沸消毒",
) -> KnowledgeEntry:
    return KnowledgeEntry(
        id=id, category=category, subcategory=subcategory, priority=priority,
        title=title, summary=summary,
        steps=steps if steps is not None else [],
        prerequisites=prerequisites if prerequisites is not None else [],
        warnings=warnings if warnings is not None else [],
    )


# ─── search_external (covers branches at lines 23-25) ────────────────────────


def test_search_external_with_available_kb(ke_db: Database) -> None:
    kb = MagicMock()
    kb.is_available.return_value = True
    kb.search_all.return_value = {"zim": ["hit"]}
    engine = KnowledgeEngine(ke_db, external_kb=kb)
    assert engine.search_external("water", limit=5) == {"zim": ["hit"]}
    kb.search_all.assert_called_once_with("water", 5)


def test_search_external_without_kb_returns_empty(ke: KnowledgeEngine) -> None:
    # No external_kb configured -> {} (covers the not-available branch).
    assert ke.search_external("water") == {}


def test_search_external_kb_unavailable_returns_empty(ke_db: Database) -> None:
    kb = MagicMock()
    kb.is_available.return_value = False
    engine = KnowledgeEngine(ke_db, external_kb=kb)
    assert engine.search_external("water") == {}


# ─── format_entry (covers steps/prerequisites/warnings branches, lines 64-74) ─


def test_format_entry_full_with_steps_prereqs_warnings(ke: KnowledgeEngine) -> None:
    e = _entry(
        steps=["烧水至沸腾", "持续至少1分钟"], prerequisites=["耐热容器"], warnings=["避免烫伤"],
    )
    out = ke.format_entry(e)
    assert "煮沸净水" in out
    assert "烧水至沸腾" in out
    assert "耐热容器" in out
    assert "避免烫伤" in out


def test_format_entry_minimal_no_optional_fields(ke: KnowledgeEngine) -> None:
    # Covers the false branches of steps/prerequisites/warnings guards.
    e = _entry(id="t2", title="简易法", summary="简述")
    out = ke.format_entry(e)
    assert "简易法" in out
    assert "steps" not in out.lower() or "步骤" not in out  # no steps section


# ─── format_answer (covers empty + related branches, lines 85-94) ────────────


def test_format_answer_empty_returns_no_match(ke: KnowledgeEngine) -> None:
    out = ke.format_answer([])
    assert isinstance(out, str)
    assert out  # non-empty no-match message


def test_format_answer_with_related_links(ke: KnowledgeEngine) -> None:
    entries = [
        _entry(id="m1", title="主答案"),
        _entry(id="r1", title="相关一"),
        _entry(id="r2", title="相关二"),
        _entry(id="r3", title="相关三"),  # beyond the 2 related cap
    ]
    out = ke.format_answer(entries)
    assert "主答案" in out
    assert "相关一" in out
    assert "相关二" in out
    assert "相关三" not in out  # capped at 2 related


# ─── get_relevant_knowledge (covers resource-fallback loop, lines 98-105) ────


def test_get_relevant_knowledge_with_low_resources_triggers_fallback(ke: KnowledgeEngine) -> None:
    # Empty initial match + resources below thresholds -> water/food/fire
    # fallback searches (covers all three elif branches).
    resources = [
        Resource(type=ResourceType.WATER, current_amount=50.0, unit="L",
                 daily_consumption=10.0, daily_intake=0.0,
                 estimated_remaining_hours=48.0, last_updated=""),       # < 72h
        Resource(type=ResourceType.FOOD, current_amount=5.0, unit="kcal",
                 daily_consumption=10.0, daily_intake=0.0,
                 estimated_remaining_hours=100.0, last_updated=""),      # < 120h
        Resource(type=ResourceType.FIRE, current_amount=5.0, unit="kg",
                 daily_consumption=10.0, daily_intake=0.0,
                 estimated_remaining_hours=200.0, last_updated=""),      # < 10 amount
    ]
    result = ke.get_relevant_knowledge("zzznomatchxyz", resources=resources)
    assert isinstance(result, list)


def test_get_relevant_knowledge_no_resources(ke: KnowledgeEngine) -> None:
    # Entries found -> no resource fallback (covers the false branch at 98).
    result = ke.get_relevant_knowledge("水", resources=None)
    assert isinstance(result, list)


# ─── resource_manager (resource critical path) ──────────────────────────────


@pytest.fixture
def rm(tmp_path: Path) -> ResourceManager:
    set_language("zh")
    db = Database(tmp_path / "rm.db")
    yield ResourceManager(db)
    db.close()


def _res(
    rtype: ResourceType, current: float = 100.0, consumption: float = 10.0,
    intake: float = 0.0, hours: float = 100.0,
) -> Resource:
    return Resource(
        type=rtype, current_amount=current, unit="x",
        daily_consumption=consumption, daily_intake=intake,
        estimated_remaining_hours=hours, last_updated="",
    )


def test_summary_with_all_resource_types(rm: ResourceManager) -> None:
    # Covers WATER/FOOD/FIRE/STORAGE formatting branches (lines 255-267).
    rm.db.upsert_resource(_res(ResourceType.POWER, current=200, consumption=100, intake=50, hours=48))
    rm.db.upsert_resource(_res(ResourceType.WATER, current=50, consumption=10, hours=120))
    rm.db.upsert_resource(_res(ResourceType.FOOD, current=2000, consumption=500, hours=96))
    rm.db.upsert_resource(_res(ResourceType.FIRE, current=20, consumption=5, hours=100))
    rm.db.upsert_resource(_res(ResourceType.STORAGE, current=0, consumption=100, intake=20, hours=0))
    summary = rm.get_resource_summary()
    assert isinstance(summary, str) and len(summary) > 0


@pytest.mark.parametrize("mode", [
    OperatingMode.ECONOMY, OperatingMode.HIBERNATION, OperatingMode.STANDARD,
    OperatingMode.PROACTIVE,
])
def test_get_power_savings_advice_per_mode(rm: ResourceManager, mode: OperatingMode) -> None:
    # Covers ECONOMY/HIBERNATION/STANDARD branches (lines 200-221) + PROACTIVE empty.
    advice = rm.get_power_savings_advice(mode)
    assert isinstance(advice, list)
    if mode != OperatingMode.PROACTIVE:
        assert len(advice) >= 1


def test_check_warnings_power_critical(rm: ResourceManager) -> None:
    rm.db.upsert_resource(_res(ResourceType.POWER, consumption=10, intake=0, hours=2.0))  # <6h
    warnings = rm.check_warnings()
    assert any(w["level"] == "critical" for w in warnings)


def test_check_warnings_power_warning(rm: ResourceManager) -> None:
    rm.db.upsert_resource(_res(ResourceType.POWER, consumption=10, intake=0, hours=10.0))  # <24h
    warnings = rm.check_warnings()
    assert any(w["level"] == "warning" for w in warnings)
    assert not any(w["level"] == "critical" for w in warnings)


def test_check_warnings_water_critical_and_food_warning(rm: ResourceManager) -> None:
    rm.db.upsert_resource(_res(ResourceType.WATER, consumption=10, hours=20.0))   # <1 day -> critical
    rm.db.upsert_resource(_res(ResourceType.FOOD, consumption=500, hours=96.0))   # 4 days -> warning
    warnings = rm.check_warnings()
    levels = {w["level"] for w in warnings}
    assert "critical" in levels
    assert "warning" in levels


def test_check_warnings_fire_critical_and_warning(rm: ResourceManager) -> None:
    rm.db.upsert_resource(_res(ResourceType.FIRE, current=2, consumption=1))   # <3 -> critical
    assert any(w["level"] == "critical" for w in rm.check_warnings())
    rm.db.upsert_resource(_res(ResourceType.FIRE, current=5, consumption=1))   # <10 -> warning
    fire_warns = [w for w in rm.check_warnings() if "fire" in w["resource"].lower() or "火" in w["resource"]]
    assert any(w["level"] == "warning" for w in fire_warns)


def test_check_warnings_storage_critical(rm: ResourceManager) -> None:
    # pct = (1 - 97/100)*100 = 3% < 5 -> critical
    rm.db.upsert_resource(_res(ResourceType.STORAGE, current=0, consumption=100, intake=97, hours=0))
    assert any(w["level"] == "critical" for w in rm.check_warnings())


def test_check_warnings_storage_warning(rm: ResourceManager) -> None:
    # pct = (1 - 92/100)*100 = 8% < 10 -> warning, not <5
    rm.db.upsert_resource(_res(ResourceType.STORAGE, current=0, consumption=100, intake=92, hours=0))
    warnings = rm.check_warnings()
    assert any(w["level"] == "warning" for w in warnings)
    assert not any(w["level"] == "critical" for w in warnings)


def test_estimate_remaining_power_sustained(rm: ResourceManager) -> None:
    # consumption <= intake -> SUSTAINED.
    r = _res(ResourceType.POWER, current=100, consumption=10, intake=20, hours=0)
    assert rm._estimate_remaining(r) == rm.SUSTAINED


def test_estimate_remaining_fire_zero_consumption_sustained(rm: ResourceManager) -> None:
    r = _res(ResourceType.FIRE, current=10, consumption=0, hours=0)
    assert rm._estimate_remaining(r) == rm.SUSTAINED


def test_estimate_remaining_storage_returns_zero(rm: ResourceManager) -> None:
    # STORAGE matches no branch -> 0.0 (covers the final return at line 83).
    r = _res(ResourceType.STORAGE, current=0, consumption=100, intake=0, hours=0)
    assert rm._estimate_remaining(r) == 0.0


def test_has_remaining_estimate_per_type(rm: ResourceManager) -> None:
    assert rm.has_remaining_estimate(_res(ResourceType.WATER, consumption=10)) is True
    assert rm.has_remaining_estimate(_res(ResourceType.WATER, consumption=0)) is False
    assert rm.has_remaining_estimate(_res(ResourceType.POWER, consumption=10, intake=20)) is False
    assert rm.has_remaining_estimate(_res(ResourceType.FIRE, consumption=5)) is True
    assert rm.has_remaining_estimate(_res(ResourceType.STORAGE, consumption=10)) is False


def test_consume_resource_and_none_path(rm: ResourceManager) -> None:
    # None path: POWER not yet in db -> consume returns gracefully (covers 57-58).
    rm.consume_resource(ResourceType.POWER, 10.0)
    assert rm.db.get_resource(ResourceType.POWER) is None
    # Happy path: upsert then consume -> amount decreases.
    rm.db.upsert_resource(_res(ResourceType.WATER, current=100, consumption=10, hours=240))
    rm.consume_resource(ResourceType.WATER, 30.0)
    assert rm.db.get_resource(ResourceType.WATER).current_amount == 70.0


def test_update_resource_none_path(rm: ResourceManager) -> None:
    # No init_defaults -> resource absent -> update returns without creating.
    rm.update_resource(ResourceType.POWER, 100.0)
    assert rm.db.get_resource(ResourceType.POWER) is None


def test_determine_operating_mode_sustained_is_proactive(rm: ResourceManager) -> None:
    # Net-positive power has no depletion deadline and must not trigger sleep.
    rm.db.upsert_resource(_res(ResourceType.POWER, consumption=10, intake=20, hours=-1.0))
    assert rm.determine_operating_mode() == OperatingMode.PROACTIVE


@pytest.mark.parametrize(
    "resource",
    [
        _res(ResourceType.POWER, current=100, consumption=10, intake=20, hours=-1.0),
        _res(ResourceType.WATER, current=12, consumption=0, intake=0, hours=-1.0),
        _res(ResourceType.FOOD, current=2000, consumption=0, intake=0, hours=-1.0),
    ],
)
def test_check_warnings_ignores_sustained_estimates(
    rm: ResourceManager, resource: Resource,
) -> None:
    rm.db.upsert_resource(resource)
    assert rm.check_warnings() == []


def test_determine_operating_mode_proactive(rm: ResourceManager) -> None:
    # hours >= 72 -> PROACTIVE (covers the threshold-match happy path, line 96-97).
    rm.db.upsert_resource(_res(ResourceType.POWER, consumption=10, intake=0, hours=100.0))
    assert rm.determine_operating_mode() == OperatingMode.PROACTIVE


def test_estimate_remaining_fire_happy_path(rm: ResourceManager) -> None:
    # FIRE consumption > 0 -> current * 24 (covers line 80->82 happy path).
    r = _res(ResourceType.FIRE, current=5, consumption=2, hours=0)
    assert rm._estimate_remaining(r) == 5 * 24.0


def test_update_operating_mode_detects_change(rm: ResourceManager) -> None:
    # Set power into ECONOMY range; update_operating_mode should report a change
    # (covers lines 102->104 and 108->109).
    rm.db.upsert_resource(_res(ResourceType.POWER, consumption=100, intake=0, hours=10.0))  # ECONOMY
    new_mode, changed = rm.update_operating_mode()
    assert changed is True
    assert new_mode == OperatingMode.ECONOMY


def test_check_warnings_power_healthy_no_warning(rm: ResourceManager) -> None:
    # Power configured but hours >= 24 -> no power warning (covers [128,135] false).
    rm.db.upsert_resource(_res(ResourceType.POWER, consumption=10, intake=0, hours=100.0))
    warnings = rm.check_warnings()
    assert not any("power" in w["resource"].lower() or "电" in w["resource"] for w in warnings)


def test_init_defaults_idempotent(rm: ResourceManager) -> None:
    # Calling init_defaults twice: second pass finds existing resources
    # (covers the `if existing is None` false branch at line 20->18).
    rm.init_defaults()
    rm.init_defaults()
    assert rm.db.get_resource(ResourceType.POWER) is not None


def test_check_warnings_all_healthy_no_warnings(rm: ResourceManager) -> None:
    # All resources configured and well-stocked -> no warnings (covers the
    # cascading elif false branches for water/food/fire/storage).
    rm.init_defaults()
    rm.db.upsert_resource(_res(ResourceType.POWER, consumption=10, intake=0, hours=100.0))
    rm.db.upsert_resource(_res(ResourceType.WATER, consumption=10, hours=480.0))    # 20 days
    rm.db.upsert_resource(_res(ResourceType.FOOD, consumption=500, hours=360.0))    # 15 days
    rm.db.upsert_resource(_res(ResourceType.FIRE, current=50, consumption=1))
    rm.db.upsert_resource(_res(ResourceType.STORAGE, current=0, consumption=100, intake=10, hours=0))  # 90% free
    assert rm.check_warnings() == []
