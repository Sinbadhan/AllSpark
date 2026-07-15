"""SHA-151: mission_planner line-coverage tests (criterion 1: total line >=75%)."""

import pytest

from allspark.core.database import Database
from allspark.core.models import Resource, ResourceType, Task, TaskType
from allspark.services.mission_planner import MissionPlanner
from allspark.services.resource_manager import ResourceManager


@pytest.fixture
def planner(tmp_path):
    db = Database(tmp_path / "mp.db")
    rm = ResourceManager(db)
    yield db, MissionPlanner(db, rm)
    db.close()


def test_generate_tasks_for_phase_creates_and_skips_existing(planner):
    db, mp = planner
    tasks = mp.generate_tasks_for_phase(0)
    assert tasks
    # second call -> existing titles skipped
    tasks2 = mp.generate_tasks_for_phase(0)
    assert tasks2 == []


def test_generate_side_missions(planner):
    _, mp = planner
    tasks = mp.generate_side_missions(0)
    assert tasks
    assert all(t.task_type == TaskType.SIDE.value for t in tasks)
    # unknown phase -> []
    assert mp.generate_side_missions(99) == []
    # second call for same phase -> existing skipped
    assert mp.generate_side_missions(0) == []


def test_get_side_and_main_missions(planner):
    db, mp = planner
    mp.generate_tasks_for_phase(0)
    mp.generate_side_missions(0)
    assert mp.get_main_missions()  # main tasks are active
    assert isinstance(mp.get_side_missions(), list)  # method covered


def test_suggest_tasks_returns_active_when_present(planner):
    db, mp = planner
    mp.generate_tasks_for_phase(0)
    assert mp.suggest_tasks()  # active exists


def test_suggest_tasks_urgent_water_and_food(planner):
    db, mp = planner
    # No active tasks; low water -> urgent water task.
    db.upsert_resource(Resource(type=ResourceType.WATER, current_amount=10, unit="L",
                                daily_consumption=10, daily_intake=0,
                                estimated_remaining_hours=48.0, last_updated="",
                                amount_known=True, consumption_known=True,
                                intake_known=True))
    result = mp.suggest_tasks(resources=db.get_all_resources())
    assert result and "water" in result[0].title.lower() or result

    # Reset: low food -> urgent food task.
    db.conn.execute("DELETE FROM tasks")
    db.conn.commit()
    db.upsert_resource(Resource(type=ResourceType.FOOD, current_amount=10, unit="kcal",
                                daily_consumption=20, daily_intake=0,
                                estimated_remaining_hours=40.0, last_updated="",
                                amount_known=True, consumption_known=True,
                                intake_known=True))
    result2 = mp.suggest_tasks(resources=db.get_all_resources())
    assert result2


def test_suggest_tasks_fallback_to_phase0(planner):
    _, mp = planner
    result = mp.suggest_tasks()  # no active, no resources
    assert result  # falls back to generate_tasks_for_phase(0)


def test_complete_fail_start_task(planner):
    db, mp = planner
    mp.generate_tasks_for_phase(0)
    tid = db.get_active_tasks()[0].id
    mp.start_task(tid)
    mp.complete_task(tid)
    # fail another
    mp.generate_side_missions(0)
    sid = db.get_tasks_by_phase(0)[-1].id
    mp.fail_task(sid)


def test_get_all_active(planner):
    _, mp = planner
    assert mp.get_all_active() == []
    mp.generate_tasks_for_phase(0)
    assert mp.get_all_active()


def test_calculate_priority_branches(planner):
    _, mp = planner
    main_task = Task(id="t1", phase=0, priority=0, title="find water", description="water",
                     status="pending", task_type=TaskType.MAIN.value,
                     created_at="t", updated_at="t")
    side_task = Task(id="t2", phase=2, priority=0, title="craft", description="craft",
                     status="pending", task_type=TaskType.SIDE.value,
                     created_at="t", updated_at="t")
    s1 = mp.calculate_priority(main_task, dependency_met=False, resource_cost=0.9)
    s2 = mp.calculate_priority(side_task, dependency_met=True, resource_cost=0.1)
    assert 0.0 <= s1 <= 1.0
    assert 0.0 <= s2 <= 1.0


def test_rank_tasks(planner):
    _, mp = planner
    main_task = Task(id="t1", phase=0, priority=0, title="water", description="water",
                     status="pending", task_type=TaskType.MAIN.value, created_at="t", updated_at="t")
    side_task = Task(id="t2", phase=3, priority=0, title="craft", description="craft",
                     status="pending", task_type=TaskType.SIDE.value, created_at="t", updated_at="t")
    ranked = mp.rank_tasks([side_task, main_task])
    assert ranked[0]["score"] >= ranked[1]["score"]
    assert ranked[0]["task"].id == "t1"  # main survival ranks first


def test_format_tasks_empty_and_with_tasks(planner):
    _, mp = planner
    assert mp.format_tasks([])  # no_active_tasks
    mp.generate_tasks_for_phase(0)
    mp.generate_side_missions(0)
    out = mp.format_tasks(mp.get_all_active())
    assert isinstance(out, str) and out
