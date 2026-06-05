"""Scheduled task framework for AllSpark.

Supports adaptive scheduling based on operating mode:
- Proactive (>72h power): every 4h
- Standard (24-72h): every 12h
- Economy (6-24h): critical-only
- Hibernation (<6h): paused
"""
import logging
import threading
from datetime import datetime
from typing import Callable, Optional

from allspark.core.models import OperatingMode

logger = logging.getLogger(__name__)

# Default intervals in seconds per operating mode
_MODE_INTERVALS = {
    OperatingMode.PROACTIVE: 4 * 3600,   # 4h
    OperatingMode.STANDARD: 12 * 3600,    # 12h
    OperatingMode.ECONOMY: 0,             # critical-only, no periodic
    OperatingMode.HIBERNATION: 0,         # paused
    OperatingMode.RECOVERY: 4 * 3600,     # 4h during recovery
}


class ScheduledTask:
    """A single scheduled task definition."""

    def __init__(self, name: str, handler: Callable, *,
                 interval_hours: float = 0,
                 mode_overrides: dict = None,
                 critical_only: bool = False):
        self.name = name
        self.handler = handler
        self.interval_hours = interval_hours
        self.mode_overrides = mode_overrides or {}  # OperatingMode -> hours
        self.critical_only = critical_only
        self._last_run: Optional[datetime] = None
        self._run_count = 0
        self._last_error: Optional[str] = None

    def get_interval(self, mode: OperatingMode) -> float:
        """Get interval in seconds for the given operating mode."""
        if mode in self.mode_overrides:
            return self.mode_overrides[mode] * 3600
        if self.interval_hours > 0:
            return self.interval_hours * 3600
        return _MODE_INTERVALS.get(mode, 12 * 3600)

    def should_run(self, mode: OperatingMode) -> bool:
        """Check if this task should run given the current mode and time."""
        if mode == OperatingMode.HIBERNATION and not self.critical_only:
            return False
        if mode == OperatingMode.ECONOMY and not self.critical_only:
            return False

        interval = self.get_interval(mode)
        if interval <= 0:
            return False

        if self._last_run is None:
            return True

        elapsed = (datetime.now() - self._last_run).total_seconds()
        return elapsed >= interval

    def execute(self) -> dict:
        """Run the task handler."""
        try:
            result = self.handler()
            self._last_run = datetime.now()
            self._run_count += 1
            self._last_error = None
            return {"task": self.name, "status": "ok", "result": result}
        except Exception as e:
            self._last_error = str(e)
            logger.warning(f"Scheduled task '{self.name}' failed: {e}")
            return {"task": self.name, "status": "error", "error": str(e)}


class TaskScheduler:
    """Adaptive task scheduler that adjusts frequency based on operating mode."""

    def __init__(self, get_mode: Callable[[], OperatingMode] = None):
        self._tasks: dict[str, ScheduledTask] = {}
        self._get_mode = get_mode or (lambda: OperatingMode.STANDARD)
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def register(self, task: ScheduledTask):
        self._tasks[task.name] = task

    def unregister(self, name: str):
        self._tasks.pop(name, None)

    def tick(self) -> list[dict]:
        """Run all tasks that are due. Returns list of results."""
        mode = self._get_mode()
        results = []
        for task in self._tasks.values():
            if task.should_run(mode):
                result = task.execute()
                results.append(result)
        return results

    def start(self, check_interval: float = 60.0):
        """Start the scheduler loop in a background thread."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()

        def _loop():
            while not self._stop_event.is_set():
                try:
                    self.tick()
                except Exception as e:
                    logger.error(f"Scheduler tick error: {e}")
                self._stop_event.wait(check_interval)

        self._thread = threading.Thread(target=_loop, daemon=True, name="allspark-scheduler")
        self._thread.start()

    def stop(self):
        """Stop the scheduler loop."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def get_status(self) -> dict:
        """Get scheduler status and task info."""
        mode = self._get_mode()
        tasks = []
        for task in self._tasks.values():
            tasks.append({
                "name": task.name,
                "last_run": task._last_run.isoformat() if task._last_run else None,
                "run_count": task._run_count,
                "last_error": task._last_error,
                "interval_hours": task.get_interval(mode) / 3600,
                "critical_only": task.critical_only,
            })
        return {
            "running": self._running,
            "mode": mode.value,
            "tasks": tasks,
        }


def create_default_scheduler(container) -> TaskScheduler:
    """Create a scheduler with default AllSpark tasks."""
    from allspark.core.models import OperatingMode

    def get_mode():
        try:
            state = container.get("resource_manager")
            if state:
                db = container.db
                if db:
                    os = db.get_operating_state()
                    return OperatingMode(os.mode)
        except Exception:
            pass
        return OperatingMode.STANDARD

    scheduler = TaskScheduler(get_mode=get_mode)

    # Resource check task
    def check_resources():
        rm = container.get("resource_manager")
        if rm:
            return rm.check_warnings()
        return []

    scheduler.register(ScheduledTask(
        name="resource_check",
        handler=check_resources,
        mode_overrides={
            OperatingMode.PROACTIVE: 4,
            OperatingMode.STANDARD: 12,
        },
    ))

    # Daily briefing task
    def generate_briefing():
        briefing = container.get("daily_briefing")
        if briefing:
            return briefing.generate()
        return None

    scheduler.register(ScheduledTask(
        name="daily_briefing",
        handler=generate_briefing,
        interval_hours=24,
    ))

    # Heartbeat task
    def update_heartbeat():
        bm = container.get("boot_manager")
        if bm:
            bm.update_heartbeat()
        return "ok"

    scheduler.register(ScheduledTask(
        name="heartbeat",
        handler=update_heartbeat,
        interval_hours=1,
    ))

    # Psychology self-assessment reminder (every 7 days)
    def check_psychology():
        psych = container.get("psychology")
        if psych:
            return psych.check_and_trigger_intervention()
        return None

    scheduler.register(ScheduledTask(
        name="psychology_check",
        handler=check_psychology,
        interval_hours=168,  # 7 days
    ))

    # Goal review task (PRD §10.2) — auto-generate + recalculate priorities + check progress
    def review_goals():
        ge = container.get("goal_engine")
        if not ge:
            return None
        calc = container.get("priority_calculator")
        return ge.review_goals(calc)

    scheduler.register(ScheduledTask(
        name="goal_review",
        handler=review_goals,
        mode_overrides={
            OperatingMode.PROACTIVE: 4,
            OperatingMode.STANDARD: 12,
        },
        # ECONOMY and HIBERNATION: not run (no mode_overrides entry → 0 interval)
    ))

    # Critical goal deadline check — runs even in ECONOMY mode (PRD §10.2)
    def check_critical_goals():
        ge = container.get("goal_engine")
        if not ge:
            return None
        notifications = ge.check_goal_progress()
        # Only return critical-priority notifications
        critical = [n for n in notifications if n.get("priority") == "critical"]
        return critical

    scheduler.register(ScheduledTask(
        name="goal_critical_check",
        handler=check_critical_goals,
        interval_hours=24,
        critical_only=True,  # Runs in ECONOMY mode too
    ))

    return scheduler
