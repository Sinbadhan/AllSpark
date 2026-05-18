from datetime import datetime
from typing import Optional

from allspark.database import Database
from allspark.models import Task, SurvivalPhase
from allspark.config import PHASE_DESC_KEYS, PHASE_GOAL_KEYS
from allspark.resource_manager import ResourceManager
from allspark.i18n import t


class MissionPlanner:
    def __init__(self, db: Database, resource_mgr: ResourceManager):
        self.db = db
        self.resource_mgr = resource_mgr

    def generate_tasks_for_phase(self, phase: int) -> list[Task]:
        existing = self.db.get_tasks_by_phase(phase)
        existing_titles = {t.title for t in existing}
        goal_keys = PHASE_GOAL_KEYS.get(phase, [])
        desc_key = PHASE_DESC_KEYS.get(phase, "")
        tasks = []
        now = datetime.now().isoformat()
        for i, goal_key in enumerate(goal_keys):
            goal_text = t(goal_key)
            if goal_text not in existing_titles:
                desc_text = t(desc_key) if desc_key else ""
                task = Task(
                    id=f"task-{phase}-{i}",
                    phase=phase,
                    priority=phase * 10 + i,
                    title=goal_text,
                    description=f"[{desc_text}] {goal_text}" if desc_text else goal_text,
                    status="pending",
                    created_at=now,
                    updated_at=now,
                )
                self.db.save_task(task)
                tasks.append(task)
        return tasks

    def suggest_tasks(self, resources: list = None) -> list[Task]:
        active = self.db.get_active_tasks()
        if active:
            return active

        if resources:
            from allspark.models import ResourceType
            for r in resources:
                if r.type == ResourceType.WATER and r.estimated_remaining_hours < 72:
                    now = datetime.now().isoformat()
                    task = Task(
                        id=f"task-urgent-water-{datetime.now().strftime('%H%M%S')}",
                        phase=0, priority=0,
                        title=t("urgent_find_water"),
                        description=t("urgent_find_water_desc"),
                        status="pending",
                        created_at=now, updated_at=now
                    )
                    self.db.save_task(task)
                    return [task]
                if r.type == ResourceType.FOOD and r.estimated_remaining_hours < 48:
                    now = datetime.now().isoformat()
                    task = Task(
                        id=f"task-urgent-food-{datetime.now().strftime('%H%M%S')}",
                        phase=0, priority=1,
                        title=t("urgent_find_food"),
                        description=t("urgent_find_food_desc"),
                        status="pending",
                        created_at=now, updated_at=now
                    )
                    self.db.save_task(task)
                    return [task]

        return self.generate_tasks_for_phase(0)

    def complete_task(self, task_id: str):
        self.db.update_task_status(task_id, "completed")

    def fail_task(self, task_id: str):
        self.db.update_task_status(task_id, "failed")

    def start_task(self, task_id: str):
        self.db.update_task_status(task_id, "in_progress")

    def get_all_active(self) -> list[Task]:
        return self.db.get_active_tasks()

    def format_tasks(self, tasks: list[Task]) -> str:
        if not tasks:
            return t("no_active_tasks")
        lines = [t("current_tasks_label")]
        for task in tasks:
            status_icon = {"pending": "⬜", "in_progress": "🔄", "completed": "✅", "failed": "❌"}.get(task.status, "❓")
            lines.append(f"  {status_icon} [{task.id}] {task.title} (Phase {task.phase})")
            if task.description:
                lines.append(f"     {task.description}")
        return "\n".join(lines)
