from datetime import datetime
from typing import Optional

from allspark.database import Database
from allspark.models import Task, SurvivalPhase
from allspark.config import PHASE_DESCRIPTIONS, PHASE_GOALS
from allspark.resource_manager import ResourceManager


class MissionPlanner:
    def __init__(self, db: Database, resource_mgr: ResourceManager):
        self.db = db
        self.resource_mgr = resource_mgr

    def generate_tasks_for_phase(self, phase: int) -> list[Task]:
        existing = self.db.get_tasks_by_phase(phase)
        existing_titles = {t.title for t in existing}
        goals = PHASE_GOALS.get(phase, [])
        tasks = []
        now = datetime.now().isoformat()
        for i, goal in enumerate(goals):
            if goal not in existing_titles:
                task = Task(
                    id=f"task-{phase}-{i}",
                    phase=phase,
                    priority=phase * 10 + i,
                    title=goal,
                    description=f"[{PHASE_DESCRIPTIONS.get(phase, '')}] {goal}",
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
                    t = Task(
                        id=f"task-urgent-water-{datetime.now().strftime('%H%M%S')}",
                        phase=0, priority=0,
                        title="紧急：寻找安全水源",
                        description="饮水储备不足，需要立即寻找安全水源",
                        status="pending",
                        created_at=now, updated_at=now
                    )
                    self.db.save_task(t)
                    return [t]
                if r.type == ResourceType.FOOD and r.estimated_remaining_hours < 48:
                    now = datetime.now().isoformat()
                    t = Task(
                        id=f"task-urgent-food-{datetime.now().strftime('%H%M%S')}",
                        phase=0, priority=1,
                        title="紧急：寻找食物",
                        description="食物储备不足，需要立即寻找可食用资源",
                        status="pending",
                        created_at=now, updated_at=now
                    )
                    self.db.save_task(t)
                    return [t]

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
            return "暂无活跃任务。"
        lines = ["📋 当前任务："]
        for t in tasks:
            status_icon = {"pending": "⬜", "in_progress": "🔄", "completed": "✅", "failed": "❌"}.get(t.status, "❓")
            lines.append(f"  {status_icon} [{t.id}] {t.title} (Phase {t.phase})")
            if t.description:
                lines.append(f"     {t.description}")
        return "\n".join(lines)
