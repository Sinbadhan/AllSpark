"""PriorityCalculator — PRD §10.4 多维度优先级算法

五维加权计算：urgency(0.30) + impact(0.25) + feasibility(0.15) + dependency(0.15) + cost(0.15)
支持 Goal 和 Task 两种对象，可被 GoalEngine / MissionPlanner / WarningProtocol 复用。
"""

import logging

from allspark.base_service import BaseService
from allspark.core.database import Database
from allspark.core.i18n import t
from allspark.core.models import Goal, ResourceType, Task

logger = logging.getLogger(__name__)

# ─── Weight Configuration ────────────────────────────────────────────────────

W_URGENCY = 0.30
W_IMPACT = 0.25
W_FEASIBILITY = 0.15
W_DEPENDENCY = 0.15
W_COST = 0.15

# Category → impact score mapping
_IMPACT_MAP = {
    "survival": 0.9,
    "quality": 0.6,
    "exploration": 0.4,
    "community": 0.5,
    "civilization": 0.3,
}

# Resource type → urgency threshold hours
_URGENCY_THRESHOLDS = {
    ResourceType.POWER: 24,
    ResourceType.WATER: 72,
    ResourceType.FOOD: 120,
    ResourceType.FIRE: 48,
    ResourceType.STORAGE: 168,
}

# Priority tier boundaries
_TIER_CRITICAL = 0.8
_TIER_HIGH = 0.6
_TIER_MEDIUM = 0.4


class PriorityCalculator(BaseService):
    SERVICE_NAME = "priority_calculator"

    def __init__(self, db: Database, **kwargs):
        super().__init__(db, **kwargs)
        self._resource_mgr = kwargs.get("resource_mgr")

    def calculate(self, goal_or_task, context: dict | None = None) -> float:
        """Calculate multi-dimensional priority score in [0, 1].

        Args:
            goal_or_task: A Goal or Task instance.
            context: Optional dict with overrides:
                - urgency, impact, feasibility, dependency_met, resource_cost
                - survivor_skills: list[str] for feasibility matching
                - is_multiplayer: bool for group impact boost
        """
        ctx = context or {}

        urgency = self._calc_urgency(goal_or_task, ctx)
        impact = self._calc_impact(goal_or_task, ctx)
        feasibility = self._calc_feasibility(goal_or_task, ctx)
        dependency = self._calc_dependency(goal_or_task, ctx)
        cost = self._calc_cost(goal_or_task, ctx)

        # Allow explicit overrides
        urgency = ctx.get("urgency", urgency)
        impact = ctx.get("impact", impact)
        feasibility = ctx.get("feasibility", feasibility)
        dependency = 1.0 if ctx.get("dependency_met", True) else 0.2
        cost = ctx.get("resource_cost", cost)

        score = (
            W_URGENCY * urgency
            + W_IMPACT * impact
            + W_FEASIBILITY * feasibility
            + W_DEPENDENCY * dependency
            + W_COST * (1.0 - cost)  # lower cost = higher priority
        )

        # Task type factor: side missions are lower priority
        if isinstance(goal_or_task, Task) and goal_or_task.task_type == "side":
            score *= 0.6

        return round(min(1.0, max(0.0, score)), 3)

    def score_to_priority(self, score: float) -> str:
        """Map numeric score to priority tier string."""
        if score >= _TIER_CRITICAL:
            return "critical"
        if score >= _TIER_HIGH:
            return "high"
        if score >= _TIER_MEDIUM:
            return "medium"
        return "low"

    def explain(self, goal_or_task, context: dict | None = None) -> str:
        """Return a human-readable explanation of the priority calculation."""
        ctx = context or {}
        urgency = self._calc_urgency(goal_or_task, ctx)
        impact = self._calc_impact(goal_or_task, ctx)
        feasibility = self._calc_feasibility(goal_or_task, ctx)
        dependency = self._calc_dependency(goal_or_task, ctx)
        cost = self._calc_cost(goal_or_task, ctx)

        title = getattr(goal_or_task, "title", str(goal_or_task))
        score = self.calculate(goal_or_task, ctx)
        tier = self.score_to_priority(score)

        parts = [
            t("priority_explain_title", title=title, tier=tier, score=score),
            t("priority_explain_urgency", value=f"{urgency:.2f}"),
            t("priority_explain_impact", value=f"{impact:.2f}"),
            t("priority_explain_feasibility", value=f"{feasibility:.2f}"),
            t("priority_explain_dependency", value=f"{dependency:.2f}"),
            t("priority_explain_cost", value=f"{cost:.2f}"),
        ]
        return "\n".join(parts)

    # ─── Dimension Calculators ────────────────────────────────────────────

    def _calc_urgency(self, obj, ctx: dict) -> float:
        """Urgency based on resource remaining time vs thresholds or deadline proximity."""
        # Explicit override
        if "urgency" in ctx:
            return ctx["urgency"]

        # Deadline-based urgency for Goals
        if isinstance(obj, Goal) and obj.deadline:
            from datetime import datetime
            try:
                dl = datetime.fromisoformat(obj.deadline)
                remaining = (dl - datetime.now()).total_seconds() / 3600
                if remaining <= 0:
                    return 1.0
                # Normalize: urgency = 1 - (remaining / deadline_total)
                # Approximate total from category
                total_hours = max(remaining, 1)
                if obj.category == "survival":
                    total_hours = 72
                elif obj.category == "quality":
                    total_hours = 336
                elif obj.category == "exploration":
                    total_hours = 720
                else:
                    total_hours = max(remaining * 2, 24)
                return min(1.0, 1.0 - remaining / total_hours)
            except (ValueError, TypeError):
                pass

        # Phase-based urgency (Tasks and Goals without deadline)
        phase = getattr(obj, "phase", None)
        if phase is not None:
            # Phase 0 = immediate survival → high urgency
            return max(0.0, 1.0 - phase * 0.2)

        # Resource-based urgency
        if self._resource_mgr and isinstance(obj, Goal):
            category_resource_map = {
                "survival": [ResourceType.WATER, ResourceType.FOOD, ResourceType.POWER],
                "quality": [ResourceType.FIRE, ResourceType.STORAGE],
            }
            for rtype in category_resource_map.get(obj.category, []):
                r = self.db.get_resource(rtype)
                if (
                    r
                    and self._resource_mgr.has_complete_rate_data(r)
                    and r.estimated_remaining_hours > 0
                ):
                    threshold = _URGENCY_THRESHOLDS.get(rtype, 72)
                    ratio = r.estimated_remaining_hours / threshold
                    if ratio < 1.0:
                        return min(1.0, 1.0 - ratio * 0.5)

        return 0.5

    def _calc_impact(self, obj, ctx: dict) -> float:
        """Impact based on category and multiplayer factor."""
        if "impact" in ctx:
            return ctx["impact"]

        category = getattr(obj, "category", "survival")
        impact = _IMPACT_MAP.get(category, 0.5)

        # Survival keywords boost
        title = getattr(obj, "title", "").lower()
        desc = getattr(obj, "description", "").lower()
        survival_keywords = {"water", "food", "shelter", "medical", "safety",
                             "水", "食物", "庇护", "医疗", "安全"}
        if any(kw in title or kw in desc for kw in survival_keywords):
            impact = min(1.0, impact * 1.2)

        # Multiplayer group benefit boost
        if ctx.get("is_multiplayer"):
            impact = min(1.0, impact * 1.1)

        return round(impact, 3)

    def _calc_feasibility(self, obj, ctx: dict) -> float:
        """Feasibility based on survivor skills matching goal/task keywords."""
        if "feasibility" in ctx:
            return ctx["feasibility"]

        skills = ctx.get("survivor_skills", [])
        if not skills:
            return 0.5

        title = getattr(obj, "title", "").lower()
        desc = getattr(obj, "description", "").lower()
        text = f"{title} {desc}"

        # Count skill matches
        matches = sum(1 for skill in skills if skill.lower() in text)
        if matches == 0:
            return 0.4
        if matches == 1:
            return 0.6
        if matches == 2:
            return 0.8
        return 0.9

    def _calc_dependency(self, obj, ctx: dict) -> float:
        """Dependency score: 1.0 if no blocking dependencies, lower if blocked."""
        if not ctx.get("dependency_met", True):
            return 0.2

        # Check for pending prerequisite tasks
        if isinstance(obj, Goal):
            # Goals with milestone progress already started are more feasible
            if obj.milestone_done and obj.milestone_count:
                progress = obj.milestone_done / obj.milestone_count
                return 0.5 + 0.5 * progress

        return 1.0

    def _calc_cost(self, obj, ctx: dict) -> float:
        """Resource cost estimate: 0 = free, 1 = very expensive."""
        if "resource_cost" in ctx:
            return ctx["resource_cost"]

        # Phase-based cost: early phases need critical physical resources
        phase = getattr(obj, "phase", None)
        if phase is not None:
            if phase <= 1:
                return 0.3  # urgent but physically cheap
            if phase <= 2:
                return 0.5
            return 0.7  # long-term projects are time-expensive

        # Category-based cost for Goals
        category = getattr(obj, "category", "survival")
        cost_map = {"survival": 0.2, "quality": 0.4, "exploration": 0.6,
                    "community": 0.5, "civilization": 0.7}
        return cost_map.get(category, 0.5)
