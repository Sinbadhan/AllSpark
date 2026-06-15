"""WarningProtocol — PRD §3.1.3 资源预警协议闭环

六步闭环：
①计算剩余时间 → ②评估获取方案 → ③排列行动方案 → ④按人格模式通知
→ ⑤追踪执行进度 → ⑥失败后重新评估

步骤①由 ResourceManager.check_warnings() 完成，
本服务负责步骤②-⑥的闭环。
"""

import logging
import uuid
from datetime import datetime

from allspark.base_service import BaseService
from allspark.core.database import Database
from allspark.core.i18n import mark, t
from allspark.core.models import ActionPlan, ResourceType

logger = logging.getLogger(__name__)

# Fallback survival heuristics when knowledge engine returns nothing
_FALLBACK_SOLUTIONS = {
    ResourceType.POWER: [
        {"title_key": "wp_power_solar", "steps_keys": ["wp_power_solar_s1", "wp_power_solar_s2", "wp_power_solar_s3"]},
        {"title_key": "wp_power_generator", "steps_keys": ["wp_power_generator_s1", "wp_power_generator_s2"]},
        {"title_key": "wp_power_conserve", "steps_keys": ["wp_power_conserve_s1", "wp_power_conserve_s2"]},
    ],
    ResourceType.WATER: [
        {"title_key": "wp_water_collect", "steps_keys": ["wp_water_collect_s1", "wp_water_collect_s2", "wp_water_collect_s3"]},
        {"title_key": "wp_water_purify", "steps_keys": ["wp_water_purify_s1", "wp_water_purify_s2"]},
        {"title_key": "wp_water_conserve", "steps_keys": ["wp_water_conserve_s1", "wp_water_conserve_s2"]},
    ],
    ResourceType.FOOD: [
        {"title_key": "wp_food_forage", "steps_keys": ["wp_food_forage_s1", "wp_food_forage_s2"]},
        {"title_key": "wp_food_hunt", "steps_keys": ["wp_food_hunt_s1", "wp_food_hunt_s2"]},
        {"title_key": "wp_food_ration", "steps_keys": ["wp_food_ration_s1", "wp_food_ration_s2"]},
    ],
    ResourceType.FIRE: [
        {"title_key": "wp_fire_source", "steps_keys": ["wp_fire_source_s1", "wp_fire_source_s2"]},
        {"title_key": "wp_fire_fuel", "steps_keys": ["wp_fire_fuel_s1", "wp_fire_fuel_s2"]},
    ],
    ResourceType.STORAGE: [
        {"title_key": "wp_storage_clean", "steps_keys": ["wp_storage_clean_s1", "wp_storage_clean_s2"]},
    ],
}


class WarningProtocol(BaseService):
    SERVICE_NAME = "warning_protocol"

    def __init__(self, db: Database, **kwargs):
        super().__init__(db, **kwargs)
        self._container = kwargs.get("container")

    # ─── Step ②: Evaluate Solutions ──────────────────────────────────────

    def evaluate_solutions(self, warning: dict) -> list[ActionPlan]:
        """Step ②: Evaluate available solutions for a resource warning.

        Queries KnowledgeEngine for relevant entries, then falls back to
        hardcoded heuristics if nothing found.
        """
        resource_str = warning.get("resource", "")
        rtype = self._parse_resource_type(resource_str)
        plans = []

        # Try knowledge engine first
        ke = self._container.get("knowledge") if self._container else None
        if ke:
            search_terms = self._build_search_terms(warning, rtype)
            for term in search_terms:
                entries = ke.search(term, limit=3)
                for entry in entries:
                    plans.append(self._entry_to_plan(entry, warning))

        # Fallback to hardcoded heuristics
        if not plans and rtype in _FALLBACK_SOLUTIONS:
            for fallback in _FALLBACK_SOLUTIONS[rtype]:
                title = t(fallback["title_key"])
                steps = [t(skey) for skey in fallback["steps_keys"]]
                plans.append(ActionPlan(
                    id=f"plan-{uuid.uuid4().hex[:6]}",
                    warning_id=warning.get("resource", "unknown"),
                    resource_type=resource_str,
                    solution_source="fallback",
                    steps=steps,
                    rank_score=0.0,
                    status="proposed",
                    created_at=datetime.now().isoformat(),
                    updated_at=datetime.now().isoformat(),
                    result="",
                    title=title,
                ))

        return plans

    # ─── Step ③: Rank Action Plans ───────────────────────────────────────

    def rank_action_plans(self, plans: list[ActionPlan]) -> list[ActionPlan]:
        """Step ③: Rank action plans using PriorityCalculator."""
        calc = self._container.get("priority_calculator") if self._container else None
        if not calc:
            # If scores already exist, preserve them; otherwise use step count
            # (fewer steps = faster = higher score).
            if not any(plan.rank_score > 0 for plan in plans):
                for plan in plans:
                    plan.rank_score = 1.0 / (len(plan.steps) + 1)
            return sorted(plans, key=lambda p: p.rank_score, reverse=True)

        for plan in plans:
            context = {
                "urgency": 0.8,  # warning-driven, so high urgency
                "impact": 0.9 if "critical" in str(plan.warning_id) else 0.6,
                "feasibility": 0.7,
                "resource_cost": min(1.0, len(plan.steps) * 0.15),
            }
            plan.rank_score = calc.calculate(
                type("Obj", (), {"title": plan.title, "description": "", "category": "survival", "phase": 0})(),
                context,
            )

        return sorted(plans, key=lambda p: p.rank_score, reverse=True)

    # ─── Step ④: Notify by Personality ──────────────────────────────────

    def notify_by_personality(self, warning: dict, plans: list[ActionPlan]) -> str:
        """Step ④: Format notification based on personality mode.

        Crisis mode: only top plan, imperative tone.
        Other modes: top 3 plans, explanatory tone.
        """
        personality = self._container.get("personality") if self._container else None
        mode = "stable"
        if personality:
            mode = personality.current_mode if hasattr(personality, "current_mode") else "stable"

        level = warning.get("level", "warning")
        message = warning.get("message", "")

        # Critical warnings default to crisis-style output even without a
        # PersonalitySystem instance.
        if mode == "crisis" or level == "critical":
            # Crisis: only the best plan, imperative
            top = plans[0] if plans else None
            lines = [f"[bold red]⚠ {message}[/]"]
            if top:
                lines.append(f"[red]→ {top.title}[/]")
                for i, step in enumerate(top.steps[:3], 1):
                    lines.append(f"  {i}. {step}")
            return "\n".join(lines)

        # Other modes: top 3 plans, explanatory
        lines = [f"[yellow]⚠ {message}[/]" if level == "warning" else f"[bold red]🔴 {message}[/]"]
        for plan in plans[:3]:
            icon = "🟢" if plan.rank_score >= 0.7 else "🟡" if plan.rank_score >= 0.4 else "⚪"
            lines.append(f"  {icon} {plan.title} (score: {plan.rank_score:.2f})")
            for i, step in enumerate(plan.steps[:2], 1):
                lines.append(f"    {i}. {step}")
            if len(plan.steps) > 2:
                lines.append(f"    ... +{len(plan.steps) - 2} more")

        return "\n".join(lines)

    # ─── Step ⑤: Track Execution ───────────────────────────────────────

    def track_execution(self, plan_id: str, status: str, result: str = "") -> bool:
        """Step ⑤: Update action plan status and record timeline event."""
        plan = self.db.get_action_plan(plan_id)
        if not plan:
            return False

        plan.status = status
        plan.result = result
        plan.updated_at = datetime.now().isoformat()
        self.db.save_action_plan(plan)

        # Record timeline event if executing
        if status == "executing" and self._container:
            timeline = self._container.get("timeline")
            if timeline and hasattr(timeline, "add_event"):
                try:
                    timeline.add_event(
                        event_type="system_event",
                        title=mark("wp_plan_executing", title=plan.title),
                        description=result,
                    )
                except Exception as e:
                    logger.warning("Failed to record warning timeline event: %s", e)

        return True

    # ─── Step ⑥: Re-evaluate if Failed ────────────────────────────────

    def re_evaluate_if_failed(self, plan_id: str) -> list[ActionPlan]:
        """Step ⑥: When a plan fails, re-evaluate with alternatives.

        Excludes the failed knowledge source and re-ranks.
        If all alternatives exhausted, escalates to CRISIS personality.
        """
        failed_plan = self.db.get_action_plan(plan_id)
        if not failed_plan:
            return []

        # Re-evaluate, excluding the failed source
        warning = {"resource": failed_plan.resource_type, "level": "critical"}
        alternatives = self.evaluate_solutions(warning)

        # Filter out the failed solution
        alternatives = [p for p in alternatives if p.title != failed_plan.title]

        if not alternatives:
            # All alternatives exhausted — escalate
            personality = self._container.get("personality") if self._container else None
            if personality and hasattr(personality, "set_mode"):
                personality.set_mode("crisis")
            logger.warning("All action plans exhausted for %s, escalated to CRISIS", failed_plan.resource_type)
            return []

        return self.rank_action_plans(alternatives)

    # ─── Full Pipeline ─────────────────────────────────────────────────

    def process_warning(self, warning: dict) -> dict:
        """Orchestrate the full 6-step warning protocol for a single warning.

        Returns a summary dict for logging/display.
        """
        # Step ②: Evaluate solutions
        plans = self.evaluate_solutions(warning)

        # Step ③: Rank plans
        plans = self.rank_action_plans(plans)

        # Step ④: Format notification by personality
        notification = self.notify_by_personality(warning, plans)

        # Save plans to DB
        for plan in plans:
            self.db.save_action_plan(plan)

        return {
            "warning": warning,
            "plans": plans,
            "plan_count": len(plans),
            "notification": notification,
            "top_plan": plans[0].title if plans else None,
            "top_score": plans[0].rank_score if plans else 0,
        }

    # ─── Helpers ──────────────────────────────────────────────────────

    def _parse_resource_type(self, resource_str: str) -> ResourceType | None:
        """Parse resource string to ResourceType enum."""
        mapping = {
            "power": ResourceType.POWER, "电力": ResourceType.POWER,
            "water": ResourceType.WATER, "水": ResourceType.WATER,
            "food": ResourceType.FOOD, "食物": ResourceType.FOOD,
            "fire": ResourceType.FIRE, "火": ResourceType.FIRE,
            "storage": ResourceType.STORAGE, "存储": ResourceType.STORAGE,
        }
        return mapping.get(resource_str.lower())

    def _build_search_terms(self, warning: dict, rtype: ResourceType | None) -> list[str]:
        """Build search terms for knowledge engine based on warning context."""
        terms = []
        if rtype == ResourceType.WATER:
            terms = ["water purification", "water source", "水净化"]
        elif rtype == ResourceType.FOOD:
            terms = ["food foraging", "edible plants", "食物"]
        elif rtype == ResourceType.POWER:
            terms = ["solar panel", "generator", "电力"]
        elif rtype == ResourceType.FIRE:
            terms = ["fire making", "fire starting", "生火"]
        elif rtype == ResourceType.STORAGE:
            terms = ["storage management", "存储"]
        else:
            terms = [warning.get("resource", "survival")]
        return terms

    def _entry_to_plan(self, entry, warning: dict) -> ActionPlan:
        """Convert a KnowledgeEntry to an ActionPlan."""
        steps = entry.steps if hasattr(entry, "steps") and entry.steps else [entry.summary]
        title = entry.title if hasattr(entry, "title") else str(entry)
        return ActionPlan(
            id=f"plan-{uuid.uuid4().hex[:6]}",
            warning_id=warning.get("resource", "unknown"),
            resource_type=warning.get("resource", "unknown"),
            solution_source=getattr(entry, "id", "knowledge"),
            steps=steps,
            rank_score=0.0,
            status="proposed",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            result="",
            title=title,
        )
