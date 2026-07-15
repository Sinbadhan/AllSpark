import sqlite3

import pytest

from allspark.core.database import Database
from allspark.core.models import RESOURCE_UNITS, OperatingMode, Resource, ResourceType
from allspark.services.daily_briefing import DailyBriefing
from allspark.services.environment import EnvironmentAssessor
from allspark.services.mission_planner import MissionPlanner
from allspark.services.power_monitor import PowerMonitor, PowerReading
from allspark.services.psychology import PsychologyTracker
from allspark.services.resource_manager import ResourceManager, ResourceValidationError
from allspark.services.rule_engine import RuleEngine


@pytest.fixture
def manager(tmp_path):
    db = Database(tmp_path / "resource-contract.db")
    resource_manager = ResourceManager(db)
    resource_manager.init_defaults()
    yield resource_manager
    db.close()


def test_resource_dataclass_is_fail_closed_by_default():
    resource = Resource(type=ResourceType.WATER, current_amount=10, unit="L")
    assert resource.amount_known is False
    assert resource.consumption_known is False
    assert resource.intake_known is False
    assert resource.capacity_known is False


def test_unknown_and_confirmed_zero_are_distinct(manager):
    initial = manager.db.get_resource(ResourceType.WATER)
    assert initial is not None
    assert initial.current_amount == 0
    assert initial.amount_known is False
    assert manager.is_configured(initial) is False

    manager.update_resource(
        ResourceType.WATER,
        0,
        consumption=2,
        intake=0,
        source="user_input",
        people_count=4,
        as_of="2026-07-15T12:00:00+08:00",
    )

    confirmed = manager.db.get_resource(ResourceType.WATER)
    assert confirmed is not None
    assert confirmed.current_amount == 0
    assert confirmed.amount_known is True
    assert confirmed.consumption_known is True
    assert confirmed.intake_known is True
    assert confirmed.people_count == 4
    assert confirmed.source == "user_input"
    assert confirmed.as_of == "2026-07-15T12:00:00+08:00"
    assert confirmed.last_updated != confirmed.as_of
    assert manager.is_configured(confirmed) is True


def test_field_unknown_clears_old_value_and_certainty(manager):
    manager.update_resource(ResourceType.FOOD, 5000, consumption=2000, intake=20)
    manager.update_resource(
        ResourceType.FOOD,
        4000,
        consumption=None,
        intake=None,
        amount_known=True,
        consumption_known=False,
        intake_known=False,
    )

    food = manager.db.get_resource(ResourceType.FOOD)
    assert food is not None
    assert food.current_amount == 4000
    assert food.amount_known is True
    assert food.daily_consumption == 0
    assert food.daily_intake == 0
    assert food.consumption_known is False
    assert food.intake_known is False
    assert manager.has_remaining_estimate(food) is False


@pytest.mark.parametrize(
    ("intake", "intake_known", "expected"),
    [
        (0, True, 120.0),
        (1, True, 240.0),
        (2, True, ResourceManager.SUSTAINED),
        (3, True, ResourceManager.SUSTAINED),
        (None, False, None),
    ],
)
def test_remaining_time_uses_net_daily_intake(manager, intake, intake_known, expected):
    manager.update_resource(
        ResourceType.WATER,
        10,
        consumption=2,
        intake=intake,
        intake_known=intake_known,
    )
    water = manager.db.get_resource(ResourceType.WATER)
    if expected is None:
        assert manager.has_complete_rate_data(water) is False
        assert manager.has_remaining_estimate(water) is False
    else:
        assert manager.estimate_remaining(water) == expected


@pytest.mark.parametrize(
    ("kwargs", "field", "reason"),
    [
        ({"source": "internet"}, "source", "invalid_source"),
        ({"people_count": "many"}, "people_count", "not_integer"),
        ({"people_count": 1.5}, "people_count", "not_integer"),
        ({"people_count": True}, "people_count", "not_integer"),
        ({"people_count": "2.0"}, "people_count", "not_integer"),
        ({"people_count": 0}, "people_count", "people_range"),
        ({"as_of": "yesterday"}, "as_of", "invalid_timestamp"),
        ({"as_of": True}, "as_of", "invalid_timestamp"),
        ({"as_of": 123}, "as_of", "invalid_timestamp"),
        ({"as_of": {}}, "as_of", "invalid_timestamp"),
        ({"source": {}}, "source", "invalid_source"),
        ({"amount_known": "yes"}, "amount_known", "not_boolean"),
    ],
)
def test_metadata_validation_happens_before_write(manager, kwargs, field, reason):
    before = manager.db.get_resource(ResourceType.POWER)
    with pytest.raises(ResourceValidationError) as exc_info:
        manager.update_resource(ResourceType.POWER, 100, **kwargs)
    assert (exc_info.value.field, exc_info.value.reason) == (field, reason)
    assert manager.db.get_resource(ResourceType.POWER) == before


@pytest.mark.parametrize("people_count", [1, 10_000, "2"])
def test_people_count_accepts_only_integer_semantics(manager, people_count):
    manager.update_resource(ResourceType.WATER, 10, people_count=people_count)
    assert manager.db.get_resource(ResourceType.WATER).people_count == int(people_count)


def test_soft_range_requires_confirmation_but_hard_limit_never_allows_overflow(manager):
    with pytest.raises(ResourceValidationError, match="outlier_confirmation"):
        manager.update_resource(ResourceType.WATER, 100_001)
    manager.update_resource(ResourceType.WATER, 100_001, confirm_outlier=True)
    assert manager.db.get_resource(ResourceType.WATER).current_amount == 100_001

    with pytest.raises(ResourceValidationError, match="too_large"):
        manager.update_resource(
            ResourceType.WATER,
            ResourceManager.MAX_RESOURCE_VALUE + 1,
            confirm_outlier=True,
        )


def test_storage_capacity_is_explicit_and_consistent(manager):
    with pytest.raises(ResourceValidationError, match="capacity_below_remaining"):
        manager.update_resource(
            ResourceType.STORAGE,
            80,
            consumption=2,
            intake=1,
            capacity=64,
        )
    manager.update_resource(
        ResourceType.STORAGE,
        80,
        consumption=2,
        intake=1,
        capacity=100,
    )
    storage = manager.db.get_resource(ResourceType.STORAGE)
    assert storage.capacity_known is True
    assert storage.capacity == 100
    assert storage.estimated_remaining_hours == 1920

    with pytest.raises(ResourceValidationError, match="capacity_storage_only"):
        manager.update_resource(ResourceType.WATER, 10, capacity=20)


def test_consume_uses_mixed_source_and_oldest_snapshot_when_rates_are_retained(
    manager,
):
    manager.update_resource(
        ResourceType.WATER,
        10,
        consumption=2,
        as_of="2026-07-15T10:00:00+08:00",
        source="estimate",
    )
    manager.consume_resource(
        ResourceType.WATER,
        1,
        source="user_input",
        as_of="2026-07-15T11:00:00+08:00",
    )
    water = manager.db.get_resource(ResourceType.WATER)
    assert water.current_amount == 9
    assert water.source == "mixed"
    assert water.as_of == "2026-07-15T10:00:00+08:00"


def test_consume_uses_new_source_and_time_without_retained_known_fields(manager):
    manager.update_resource(
        ResourceType.WATER,
        10,
        as_of="2026-07-15T10:00:00+08:00",
        source="estimate",
    )
    manager.consume_resource(
        ResourceType.WATER,
        1,
        source="user_input",
        as_of="2026-07-15T11:00:00+08:00",
    )
    water = manager.db.get_resource(ResourceType.WATER)
    assert water.current_amount == 9
    assert water.consumption_known is False
    assert water.intake_known is False
    assert water.source == "user_input"
    assert water.as_of == "2026-07-15T11:00:00+08:00"


def test_consume_rejects_unknown_inventory_without_write(manager):
    manager.mark_unknown(
        ResourceType.WATER,
        as_of="2026-07-15T10:00:00+08:00",
    )
    before = manager.db.get_resource(ResourceType.WATER)
    with pytest.raises(ResourceValidationError, match="unknown_inventory"):
        manager.consume_resource(
            ResourceType.WATER,
            1,
            as_of="2026-07-15T11:00:00+08:00",
        )
    assert manager.db.get_resource(ResourceType.WATER) == before


@pytest.mark.parametrize("as_of", [True, 123, {}, "", "not-a-time", "2999-01-01T00:00:00Z"])
def test_consume_rejects_malformed_or_future_snapshot_before_write(manager, as_of):
    manager.update_resource(ResourceType.WATER, 10, consumption=2, intake=0)
    before = manager.db.get_resource(ResourceType.WATER)
    with pytest.raises(ResourceValidationError):
        manager.consume_resource(ResourceType.WATER, 1, as_of=as_of)
    assert manager.db.get_resource(ResourceType.WATER) == before


def test_incomplete_power_rate_never_upgrades_to_proactive(manager):
    manager.update_resource(ResourceType.POWER, 500, consumption=20, intake=None)
    assert manager.determine_operating_mode() == OperatingMode.STANDARD
    assert PowerMonitor(db=manager.db).estimate_runtime() == {
        "estimated_hours": None,
        "mode_recommendation": "unknown",
    }


def test_power_monitor_controlled_sources_and_shared_fire_formula(manager):
    monitor = PowerMonitor(db=manager.db, resource_manager=manager)
    monitor._update_db(
        PowerReading(
            timestamp="2026-07-15T09:00:00+08:00",
            energy_wh=400,
            power_w=10,
            charging=True,
        )
    )
    sensor_power = manager.db.get_resource(ResourceType.POWER)
    assert sensor_power.amount_known is True
    assert sensor_power.consumption_known is False
    assert sensor_power.intake_known is True
    assert sensor_power.source == "sensor"
    assert sensor_power.as_of == "2026-07-15T09:00:00+08:00"

    monitor.manual_input(300, daily_consumption=100, daily_intake=20)
    manual_power = manager.db.get_resource(ResourceType.POWER)
    assert manual_power.source == "user_input"
    assert manual_power.amount_known is True
    assert manual_power.consumption_known is True
    assert manual_power.intake_known is True

    fire = Resource(
        type=ResourceType.FIRE,
        current_amount=10,
        unit="uses",
        daily_consumption=2,
        daily_intake=0,
        amount_known=True,
        consumption_known=True,
        intake_known=True,
    )
    assert monitor._estimate_hours(fire) == 120


def test_partial_power_reading_preserves_energy_without_inventing_rate_state(manager):
    manager.update_resource(
        ResourceType.POWER,
        500,
        consumption=None,
        intake=None,
        consumption_known=False,
        intake_known=False,
    )
    reading = PowerMonitor(db=manager.db, resource_manager=manager)._read_simulated()
    assert reading.source == "from_db_partial"
    assert reading.energy_wh == 500
    assert reading.battery_percent == 0
    assert reading.charging is False


def test_partial_sensor_merge_uses_mixed_source_and_oldest_snapshot(manager):
    manager.update_resource(
        ResourceType.POWER,
        500,
        consumption=100,
        intake=0,
        source="user_input",
        as_of="2026-07-15T09:00:00+08:00",
    )
    monitor = PowerMonitor(db=manager.db, resource_manager=manager)
    monitor._update_db(
        PowerReading(
            timestamp="2026-07-15T12:00:00+08:00",
            energy_wh=400,
            power_w=0,
            charging=False,
        )
    )
    power = manager.db.get_resource(ResourceType.POWER)
    assert power.current_amount == 400
    assert power.daily_consumption == 100
    assert power.daily_intake == 0
    assert power.source == "mixed"
    assert power.as_of == "2026-07-15T09:00:00+08:00"


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"amount": True}, "amount"),
        ({"amount": False}, "amount"),
        ({"amount": 10, "consumption": True}, "daily_consumption"),
        ({"amount": 10, "intake": False}, "daily_intake"),
        (
            {
                "rtype": ResourceType.STORAGE,
                "amount": 10,
                "capacity": True,
            },
            "capacity",
        ),
    ],
)
def test_boolean_resource_values_are_rejected_before_write(manager, kwargs, field):
    rtype = kwargs.pop("rtype", ResourceType.WATER)
    amount = kwargs.pop("amount")
    before = manager.db.get_resource(rtype)
    with pytest.raises(ResourceValidationError) as exc_info:
        manager.update_resource(rtype, amount, **kwargs)
    assert (exc_info.value.field, exc_info.value.reason) == (field, "not_numeric")
    assert manager.db.get_resource(rtype) == before


def test_partial_known_values_do_not_drive_user_visible_or_decision_paths(manager):
    manager.update_resource(
        ResourceType.WATER,
        10,
        consumption=2,
        intake=None,
        intake_known=False,
        as_of="2026-07-15T10:00:00+08:00",
    )
    water = manager.db.get_resource(ResourceType.WATER)
    assert water is not None

    planner = MissionPlanner(manager.db, manager)
    tasks = planner.suggest_tasks(resources=[water])
    assert all(not task.id.startswith("task-urgent-") for task in tasks)

    assessor = EnvironmentAssessor(manager.db, resource_mgr=manager)
    assert assessor._resource_status(water) == "unknown"

    briefing = DailyBriefing(manager.db, resource_mgr=manager)._resource_section()
    assert "10.0L" in briefing
    assert "0h" not in briefing
    assert "0.0d" not in briefing

    class CaptureLLM:
        available = True

        def __init__(self):
            self.context = None

        def survival_chat(self, user_input, *, context, phase):
            self.context = context
            return "ok"

    llm = CaptureLLM()
    engine = object.__new__(RuleEngine)
    engine.resource_mgr = manager
    engine.llm = llm
    engine.knowledge = None
    engine._format_trusted_response = lambda content, match: content
    RuleEngine._handle_general(engine, "status", [water], [], 0)
    assert llm.context == ""

    assert PsychologyTracker(
        manager.db, resource_mgr=manager
    )._calculate_stress() == 0


def test_database_rejects_noncanonical_unit(tmp_path):
    db = Database(tmp_path / "canonical.db")
    with pytest.raises(ValueError, match="canonical unit L"):
        db.upsert_resource(
            Resource(type=ResourceType.WATER, current_amount=5, unit="gallons")
        )
    assert db.get_resource(ResourceType.WATER) is None
    db.close()


def test_legacy_positive_resource_migrates_to_unknown_and_stays_untrusted(tmp_path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE resources (
            type TEXT PRIMARY KEY,
            current_amount REAL NOT NULL,
            unit TEXT NOT NULL,
            daily_consumption REAL DEFAULT 0,
            daily_intake REAL DEFAULT 0,
            estimated_remaining_hours REAL DEFAULT 0,
            last_updated TEXT NOT NULL
        )"""
    )
    connection.execute(
        "INSERT INTO resources VALUES (?,?,?,?,?,?,?)",
        ("power", 500, RESOURCE_UNITS[ResourceType.POWER], 100, 0, 120, "2026-01-01"),
    )
    connection.commit()
    connection.close()

    db = Database(path)
    migrated = db.get_resource(ResourceType.POWER)
    assert migrated.current_amount == 500
    assert migrated.amount_known is False
    assert migrated.consumption_known is False
    assert migrated.intake_known is False
    assert migrated.source == "migration"
    assert ResourceManager(db).determine_operating_mode() == OperatingMode.STANDARD
    assert PowerMonitor(db=db)._read_simulated().source == "no_data"
    assert PowerMonitor(db=db).estimate_runtime()["mode_recommendation"] == "unknown"
    db.close()
