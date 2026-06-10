import logging
from datetime import datetime

from allspark.core.config import PHASE_DESC_KEYS, PHASE_GOAL_KEYS
from allspark.core.database import Database
from allspark.core.i18n import t
from allspark.core.models import Task, TaskType
from allspark.services.resource_manager import ResourceManager

logger = logging.getLogger(__name__)

# Side mission templates per phase (PRD §10.1)
_SIDE_MISSION_TEMPLATES = {
    0: [
        {"title_key": "side_explore_nearby", "desc_key": "side_explore_nearby_desc"},
        {"title_key": "side_collect_materials", "desc_key": "side_collect_materials_desc"},
    ],
    1: [
        {"title_key": "side_improve_shelter", "desc_key": "side_improve_shelter_desc"},
        {"title_key": "side_map_water_sources", "desc_key": "side_map_water_sources_desc"},
    ],
    2: [
        {"title_key": "side_start_garden", "desc_key": "side_start_garden_desc"},
        {"title_key": "side_craft_tools", "desc_key": "side_craft_tools_desc"},
    ],
    3: [
        {"title_key": "side_build_radio", "desc_key": "side_build_radio_desc"},
        {"title_key": "side_document_knowledge", "desc_key": "side_document_knowledge_desc"},
    ],
    4: [
        {"title_key": "side_teach_skills", "desc_key": "side_teach_skills_desc"},
        {"title_key": "side_establish_trade", "desc_key": "side_establish_trade_desc"},
    ],
}


class MissionPlanner:
    def __init__(self, db: Database, resource_mgr: ResourceManager):
        self.db = db
        self.resource_mgr = resource_mgr

    def generate_tasks_for_phase(self, phase: int) -> list[Task]:
        existing = self.db.get_tasks_by_phase(phase)
        existing_titles = {task.title for task in existing}
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
                    task_type=TaskType.MAIN.value,
                    created_at=now,
                    updated_at=now,
                )
                self.db.save_task(task)
                tasks.append(task)
        return tasks

    def generate_side_missions(self, phase: int) -> list[Task]:
        """Generate side missions for the given phase (PRD §10.1)."""
        templates = _SIDE_MISSION_TEMPLATES.get(phase, [])
        if not templates:
            return []

        existing = self.db.get_tasks_by_phase(phase)
        existing_titles = {task.title for task in existing}
        tasks = []
        now = datetime.now().isoformat()

        for i, tmpl in enumerate(templates):
            title = t(tmpl["title_key"])
            if title in existing_titles:
                continue
            desc = t(tmpl["desc_key"])
            task = Task(
                id=f"side-{phase}-{i}",
                phase=phase,
                priority=phase * 10 + 50 + i,  # lower priority than main
                title=title,
                description=desc,
                status="pending",
                task_type=TaskType.SIDE.value,
                created_at=now,
                updated_at=now,
            )
            self.db.save_task(task)
            tasks.append(task)
        return tasks

    def get_side_missions(self) -> list[Task]:
        """Get all active side missions."""
        active = self.db.get_active_tasks()
        return [task for task in active if task.task_type == TaskType.SIDE.value]

    def get_main_missions(self) -> list[Task]:
        """Get all active main missions."""
        active = self.db.get_active_tasks()
        return [task for task in active if task.task_type != TaskType.SIDE.value]

    def suggest_tasks(self, resources: list = None) -> list[Task]:
        active = self.db.get_active_tasks()
        if active:
            return active

        if resources:
            from allspark.core.models import ResourceType
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

    def calculate_priority(self, task: Task, *,
                           urgency: float = 0.5,
                           impact: float = 0.5,
                           feasibility: float = 0.5,
                           dependency_met: bool = True,
                           resource_cost: float = 0.5) -> float:
        """Calculate multi-dimensional task priority (PRD §10.4).

        priority = f(urgency, impact, feasibility, dependency, resource_cost)
        Rules:
          - Survival > quality of life
          - Group benefit > individual benefit (multiplayer)
          - AllSpark dynamically adjusts and explains reasoning

        Returns a float in [0, 1] where higher = more important.
        """
        # Weight configuration
        W_URGENCY = 0.30
        W_IMPACT = 0.25
        W_FEASIBILITY = 0.15
        W_DEPENDENCY = 0.15
        W_COST = 0.15

        # Phase-based urgency boost: lower phase = more survival-critical
        phase_factor = max(0.0, 1.0 - task.phase * 0.2)
        adjusted_urgency = urgency * (0.5 + 0.5 * phase_factor)

        # Task type factor: main > side
        type_factor = 1.0 if task.task_type != TaskType.SIDE.value else 0.6

        # Dependency penalty
        dep_score = 1.0 if dependency_met else 0.2

        # Resource cost: lower cost is better (invert)
        cost_score = 1.0 - resource_cost

        # Feasibility: higher is better
        feas_score = feasibility

        # Impact: survival categories get boost
        survival_categories = {"water", "food", "shelter", "medical", "safety"}
        impact_boost = 1.2 if any(c in task.title.lower() or c in task.description.lower()
                                   for c in survival_categories) else 1.0
        adjusted_impact = min(1.0, impact * impact_boost)

        score = (
            W_URGENCY * adjusted_urgency +
            W_IMPACT * adjusted_impact +
            W_FEASIBILITY * feas_score +
            W_DEPENDENCY * dep_score +
            W_COST * cost_score
        ) * type_factor

        return round(min(1.0, max(0.0, score)), 3)

    def rank_tasks(self, tasks: list[Task] = None) -> list[dict]:
        """Rank tasks by multi-dimensional priority algorithm.

        Returns list of {task, priority_score, reasoning} sorted by score desc.
        """
        if tasks is None:
            tasks = self.get_all_active()

        ranked = []
        for task in tasks:
            # Estimate parameters from task properties
            urgency = 1.0 if task.phase == 0 else (0.7 if task.phase <= 1 else 0.4)
            impact = 0.8 if task.task_type != TaskType.SIDE.value else 0.4
            feasibility = 0.6  # default
            resource_cost = 0.3 if task.phase <= 1 else 0.5

            score = self.calculate_priority(
                task,
                urgency=urgency,
                impact=impact,
                feasibility=feasibility,
                dependency_met=True,
                resource_cost=resource_cost,
            )

            # Generate reasoning
            reasons = []
            if task.phase == 0:
                reasons.append("survival-critical phase")
            if task.task_type != TaskType.SIDE.value:
                reasons.append("main mission")
            if urgency > 0.7:
                reasons.append("high urgency")

            ranked.append({
                "task": task,
                "score": score,
                "reasoning": "; ".join(reasons) if reasons else "standard priority",
            })

        ranked.sort(key=lambda x: x["score"], reverse=True)
        return ranked

    def format_tasks(self, tasks: list[Task]) -> str:
        if not tasks:
            return t("no_active_tasks")
        main = [task for task in tasks if task.task_type != TaskType.SIDE.value]
        side = [task for task in tasks if task.task_type == TaskType.SIDE.value]
        lines = []
        if main:
            lines.append(t("current_tasks_label"))
            for task in main:
                status_icon = {"pending": "⬜", "in_progress": "🔄", "completed": "✅", "failed": "❌"}.get(task.status, "❓")
                lines.append(f"  {status_icon} [{task.id}] {task.title} (Phase {task.phase})")
                if task.description:
                    lines.append(f"     {task.description}")
        if side:
            lines.append(f"\n{'─' * 20}")
            lines.append(t("side_missions_label"))
            for task in side:
                status_icon = {"pending": "◇", "in_progress": "▶", "completed": "✓", "failed": "✗"}.get(task.status, "?")
                lines.append(f"  {status_icon} [{task.id}] {task.title}")
        return "\n".join(lines)
