import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

from allspark.core.i18n import mark, render, t
from allspark.core.models import Goal, Milestone, OperatingMode, ResourceType

logger = logging.getLogger(__name__)

_GOAL_TEMPLATES = [
    {
        "id_prefix": "water",
        "title_key": "goal_water_title",
        "desc_key": "goal_water_desc",
        "category": "survival",
        "priority": "critical",
        "triggers": ["water_remaining < 72h"],
        "rationale_key": "goal_water_rationale",
        "milestones_keys": [
            "goal_water_m1", "goal_water_m2", "goal_water_m3",
        ],
        "deadline_hours": 72,
    },
    {
        "id_prefix": "food",
        "title_key": "goal_food_title",
        "desc_key": "goal_food_desc",
        "category": "survival",
        "priority": "critical",
        "triggers": ["food_remaining < 120h"],
        "rationale_key": "goal_food_rationale",
        "milestones_keys": [
            "goal_food_m1", "goal_food_m2", "goal_food_m3",
        ],
        "deadline_hours": 120,
    },
    {
        "id_prefix": "shelter",
        "title_key": "goal_shelter_title",
        "desc_key": "goal_shelter_desc",
        "category": "survival",
        "priority": "high",
        "triggers": ["shelter_unsafe"],
        "rationale_key": "goal_shelter_rationale",
        "milestones_keys": [
            "goal_shelter_m1", "goal_shelter_m2", "goal_shelter_m3",
        ],
        "deadline_hours": 96,
    },
    {
        "id_prefix": "power",
        "title_key": "goal_power_title",
        "desc_key": "goal_power_desc",
        "category": "survival",
        "priority": "high",
        "triggers": ["power_remaining < 24h"],
        "rationale_key": "goal_power_rationale",
        "milestones_keys": [
            "goal_power_m1", "goal_power_m2", "goal_power_m3",
        ],
        "deadline_hours": 48,
    },
    {
        "id_prefix": "agriculture",
        "title_key": "goal_agriculture_title",
        "desc_key": "goal_agriculture_desc",
        "category": "quality",
        "priority": "medium",
        "triggers": ["phase >= 1", "basics_stable"],
        "rationale_key": "goal_agriculture_rationale",
        "milestones_keys": [
            "goal_agriculture_m1", "goal_agriculture_m2", "goal_agriculture_m3",
        ],
        "deadline_hours": 336,
    },
    {
        "id_prefix": "communication",
        "title_key": "goal_communication_title",
        "desc_key": "goal_communication_desc",
        "category": "exploration",
        "priority": "low",
        "triggers": ["phase >= 3"],
        "rationale_key": "goal_communication_rationale",
        "milestones_keys": [
            "goal_communication_m1", "goal_communication_m2",
        ],
        "deadline_hours": 720,
    },
]


class GoalEngine:
    def __init__(self, db, resource_mgr=None, survival=None):
        self.db = db
        self.resource_mgr = resource_mgr
        self.survival = survival

    def get_active_goals(self) -> list:
        return self.db.get_active_goals()

    def auto_generate_goals(self) -> list[Goal]:
        existing = self.db.get_active_goals()
        existing_prefixes = {g.id.split("-")[0] for g in existing}
        generated = []

        resources = {}
        for rtype in ResourceType:
            r = self.db.get_resource(rtype)
            if r:
                resources[rtype] = r

        phase = 0
        if self.survival:
            assessment = self.survival.assess()
            phase = assessment.get("phase", 0)

        for template in _GOAL_TEMPLATES:
            prefix = template["id_prefix"]
            if prefix in existing_prefixes:
                continue

            should_create = self._evaluate_triggers(template, resources, phase)
            if not should_create:
                continue

            goal = self._create_goal_from_template(template)
            self.db.save_goal(goal)

            for i, ms_key in enumerate(template["milestones_keys"]):
                ms = Milestone(
                    id=f"{goal.id}-m{i+1}",
                    goal_id=goal.id,
                    description=mark(ms_key),
                    done=False,
                    order=i + 1,
                    created_at=datetime.now().isoformat(),
                )
                self.db.save_milestone(ms)

            goal.milestone_count = len(template["milestones_keys"])
            self.db.save_goal(goal)
            generated.append(goal)

        return generated

    def _evaluate_triggers(self, template, resources, phase) -> bool:
        prefix = template["id_prefix"]

        if prefix == "water":
            water = resources.get(ResourceType.WATER)
            if water and water.estimated_remaining_hours > 0:
                return water.estimated_remaining_hours < 72
            return water is not None and water.current_amount > 0

        if prefix == "food":
            food = resources.get(ResourceType.FOOD)
            if food and food.estimated_remaining_hours > 0:
                return food.estimated_remaining_hours < 120
            return food is not None and food.current_amount > 0

        if prefix == "power":
            power = resources.get(ResourceType.POWER)
            if power and power.estimated_remaining_hours > 0:
                return power.estimated_remaining_hours < 24
            return False

        if prefix == "shelter":
            return False

        if prefix == "agriculture":
            return phase >= 1

        if prefix == "communication":
            return phase >= 3

        return False

    def _create_goal_from_template(self, template) -> Goal:
        now = datetime.now()
        deadline = (now + timedelta(hours=template["deadline_hours"])).isoformat()
        return Goal(
            id=f"{template['id_prefix']}-{uuid.uuid4().hex[:6]}",
            title=mark(template["title_key"]),
            description=mark(template["desc_key"]),
            goal_type="auto",
            category=template["category"],
            priority=template["priority"],
            status="active",
            source="assessment",
            progress=0.0,
            deadline=deadline,
            triggers=json.dumps(template["triggers"]),
            rationale=t(template["rationale_key"]),
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
        )

    def add_manual_goal(self, title: str, description: str = "",
                        category: str = "survival", priority: str = "medium",
                        created_by: str = "", deadline: str = "",
                        milestone_descriptions: list[str] = None) -> Goal:
        # B-14: Skip if an active goal with the same title already exists
        for g in self.db.get_active_goals():
            if g.title == title:
                return g

        now = datetime.now()
        goal = Goal(
            id=f"manual-{uuid.uuid4().hex[:6]}",
            title=title,
            description=description,
            goal_type="manual",
            category=category,
            priority=priority,
            status="active",
            source="survivor",
            progress=0.0,
            deadline=deadline,
            created_by=created_by,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
        )
        self.db.save_goal(goal)

        if milestone_descriptions:
            for i, desc in enumerate(milestone_descriptions):
                ms = Milestone(
                    id=f"{goal.id}-m{i+1}",
                    goal_id=goal.id,
                    description=desc,
                    done=False,
                    order=i + 1,
                    created_at=now.isoformat(),
                )
                self.db.save_milestone(ms)
            goal.milestone_count = len(milestone_descriptions)
            self.db.save_goal(goal)

        return goal

    def complete_milestone(self, milestone_id: str) -> Optional[Goal]:
        all_goals = self.db.get_active_goals()
        for g in all_goals:
            milestones = self.db.get_milestones_by_goal(g.id)
            for ms in milestones:
                if ms.id == milestone_id:
                    self.db.complete_milestone(milestone_id)
                    self._recalculate_progress(g.id)
                    return self.db.get_goal(g.id)
        return None

    def adjust_for_weather(self, weather_prediction: dict) -> list[dict]:
        adjustments = []
        weather_prediction.get("forecast", "unknown")
        severity = weather_prediction.get("severity", "normal")

        if severity == "severe":
            outdoor_goals = self.db.get_goals_by_category("exploration")
            for g in outdoor_goals:
                if g.status == "active" and g.priority != "critical":
                    self.pause_goal(g.id)
                    adjustments.append({
                        "goal_id": g.id,
                        "action": "paused",
                        "reason": t("goal_weather_severe_pause"),
                    })

            goals = self.db.get_active_goals()
            has_shelter = any(
                g.title and ("庇护" in render(g.title) or "shelter" in render(g.title).lower())
                for g in goals
            )
            if not has_shelter:
                goal = self.add_manual_goal(
                    title=mark("goal_weather_shelter_title"),
                    category="survival",
                    priority="high",
                    milestone_descriptions=[
                        t("goal_weather_shelter_m1"),
                        t("goal_weather_shelter_m2"),
                        t("goal_weather_shelter_m3"),
                    ],
                )
                adjustments.append({
                    "goal_id": goal.id,
                    "action": "created",
                    "reason": t("goal_weather_shelter_reason"),
                })

        elif severity == "moderate":
            goals = self.db.get_active_goals()
            for g in goals:
                if g.category == "exploration" and g.priority not in ("critical", "high"):
                    adjustments.append({
                        "goal_id": g.id,
                        "action": "suggested_pause",
                        "reason": t("goal_weather_moderate_pause"),
                    })

        return adjustments

    def _recalculate_progress(self, goal_id: str):
        milestones = self.db.get_milestones_by_goal(goal_id)
        if not milestones:
            return
        done = sum(1 for m in milestones if m.done)
        total = len(milestones)
        progress = done / total if total > 0 else 0.0
        self.db.update_goal_progress(goal_id, progress, milestone_done=done)

        if done == total:
            self.db.update_goal_status(goal_id, "completed")

    def abandon_goal(self, goal_id: str) -> bool:
        goal = self.db.get_goal(goal_id)
        if not goal:
            return False
        if goal.priority == "critical":
            return False
        self.db.update_goal_status(goal_id, "abandoned")
        return True

    def complete_goal(self, goal_id: str) -> bool:
        goal = self.db.get_goal(goal_id)
        if not goal:
            return False
        self.db.update_goal_status(goal_id, "completed")
        return True

    def pause_goal(self, goal_id: str) -> bool:
        goal = self.db.get_goal(goal_id)
        if not goal:
            return False
        if goal.priority == "critical":
            return False
        self.db.update_goal_status(goal_id, "paused")
        return True

    def resume_goal(self, goal_id: str) -> bool:
        goal = self.db.get_goal(goal_id)
        if not goal:
            return False
        self.db.update_goal_status(goal_id, "active")
        return True

    def get_goal_detail(self, goal_id: str) -> Optional[dict]:
        goal = self.db.get_goal(goal_id)
        if not goal:
            return None
        milestones = self.db.get_milestones_by_goal(goal_id)
        return {
            "goal": goal,
            "milestones": milestones,
        }

    def get_goal_summary(self) -> str:
        goals = self.db.get_active_goals()
        if not goals:
            return t("no_active_goals")

        lines = []
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_goals = sorted(goals, key=lambda g: priority_order.get(g.priority, 99))

        for g in sorted_goals:
            icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(g.priority, "⚪")
            progress_pct = int(g.progress * 100)
            ms_info = f"{g.milestone_done}/{g.milestone_count}" if g.milestone_count > 0 else "-"
            deadline_info = ""
            if g.deadline:
                try:
                    dl = datetime.fromisoformat(g.deadline)
                    remaining = dl - datetime.now()
                    if remaining.total_seconds() > 0:
                        hours = int(remaining.total_seconds() / 3600)
                        deadline_info = f" | {hours}h"
                    else:
                        deadline_info = " | ⚠️ overdue"
                except (ValueError, TypeError) as e:
                    logger.warning(f"Failed to parse goal deadline '{g.deadline}': {e}")

            lines.append(
                f"{icon} [{g.category}] {render(g.title)}\n"
                f"   {render(g.rationale or g.description)}\n"
                f"   {t('goal_progress_label')}: {ms_info} ({progress_pct}%){deadline_info}"
            )

        return "\n".join(lines)

    def check_goal_progress(self) -> list[dict]:
        goals = self.db.get_active_goals()
        notifications = []
        now = datetime.now()

        for g in goals:
            if g.deadline:
                try:
                    dl = datetime.fromisoformat(g.deadline)
                    remaining = dl - now
                    if remaining.total_seconds() < 0:
                        notifications.append({
                            "type": "goal_overdue",
                            "goal_id": g.id,
                            "title": g.title,
                            "message": t("goal_overdue_msg", title=g.title),
                            "priority": "critical" if g.priority == "critical" else "high",
                        })
                    elif remaining.total_seconds() < 3600 * 12:
                        notifications.append({
                            "type": "goal_deadline_approaching",
                            "goal_id": g.id,
                            "title": g.title,
                            "message": t("goal_deadline_soon_msg", title=g.title),
                            "priority": g.priority,
                        })
                except (ValueError, TypeError) as e:
                    logger.warning(f"Failed to parse goal deadline '{g.deadline}': {e}")

            milestones = self.db.get_milestones_by_goal(g.id)
            for ms in milestones:
                if ms.done and not ms.completed_at:
                    notifications.append({
                        "type": "milestone_completed",
                        "goal_id": g.id,
                        "milestone_id": ms.id,
                        "title": ms.description,
                        "message": t("milestone_reached_msg", desc=ms.description),
                        "priority": "medium",
                    })

        return notifications

    def get_tracking_interval(self, mode: OperatingMode) -> int:
        intervals = {
            OperatingMode.PROACTIVE: 4 * 3600,
            OperatingMode.STANDARD: 12 * 3600,
            OperatingMode.ECONOMY: 0,
            OperatingMode.HIBERNATION: 0,
        }
        return intervals.get(mode, 12 * 3600)

    def recalculate_priorities(self, priority_calculator=None) -> int:
        """Recalculate priority for all active goals using PriorityCalculator.

        Returns the number of goals whose priority was changed.
        """
        if priority_calculator is None:
            from allspark.services.priority_calculator import PriorityCalculator
            priority_calculator = PriorityCalculator(self.db, resource_mgr=self.resource_mgr)

        goals = self.db.get_active_goals()
        changed = 0
        for g in goals:
            old_priority = g.priority
            context = {"resource_mgr": self.resource_mgr} if self.resource_mgr else {}
            score = priority_calculator.calculate(g, context)
            new_priority = priority_calculator.score_to_priority(score)

            if new_priority != old_priority:
                g.priority = new_priority
                g.updated_at = datetime.now().isoformat()
                self.db.save_goal(g)
                changed += 1

        return changed

    def review_goals(self, priority_calculator=None) -> dict:
        """Consolidated goal review: auto-generate + recalculate + check progress.

        Called by the scheduled goal_review task.
        """
        generated = self.auto_generate_goals()
        recalculated = self.recalculate_priorities(priority_calculator)
        notifications = self.check_goal_progress()

        return {
            "generated": len(generated),
            "recalculated": recalculated,
            "notifications": len(notifications),
            "generated_goals": generated,
            "notifications_list": notifications,
        }

    def sync_tasks_from_goal(self, goal_id: str) -> list:
        from allspark.core.models import Task

        goal = self.db.get_goal(goal_id)
        if not goal:
            return []

        milestones = self.db.get_milestones_by_goal(goal_id)
        existing_tasks = self.db.get_active_tasks()
        existing_titles = {t.title for t in existing_tasks}

        created = []
        now = datetime.now().isoformat()

        for ms in milestones:
            if ms.done or ms.description in existing_titles:
                continue

            phase_map = {
                "survival": 0, "quality": 1, "exploration": 2,
                "community": 3, "civilization": 4,
            }
            phase = phase_map.get(goal.category, 0)

            priority_map = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            priority = priority_map.get(goal.priority, 2)

            task = Task(
                id=f"task-{goal.id}-m{ms.order}",
                phase=phase,
                priority=priority,
                title=ms.description,
                # Pass goal.title / ms.description through verbatim — render()
                # resolves nested markers at read time, so the embedded title
                # also follows the current language.
                description=mark(
                    "task_from_goal_desc",
                    goal_title=goal.title,
                    ms_desc=ms.description,
                ),
                status="pending",
                created_at=now,
                updated_at=now,
            )
            self.db.save_task(task)
            created.append(task)

        return created

    def sync_all_goals_to_tasks(self) -> list:
        goals = self.db.get_active_goals()
        all_created = []
        for g in goals:
            created = self.sync_tasks_from_goal(g.id)
            all_created.extend(created)
        return all_created

    def on_task_completed(self, task_id: str):
        task = None
        for task_item in self.db.get_active_tasks():
            if task_item.id == task_id:
                task = task_item
                break

        if not task:
            return None

        self.db.update_task_status(task_id, "completed")

        goals = self.db.get_active_goals()
        for g in goals:
            milestones = self.db.get_milestones_by_goal(g.id)
            for ms in milestones:
                if ms.description == task.title and not ms.done:
                    self.db.complete_milestone(ms.id)
                    self._recalculate_progress(g.id)
                    updated = self.db.get_goal(g.id)
                    return updated

        return None
