"""Module import-time smoke benchmark for AllSpark.

Usage:
    python scripts/bench_import.py            # print table
    python scripts/bench_import.py --check    # also enforce soft budget; warn on overrun
    python scripts/bench_import.py --check --hard-fail
                                              # also exit 1 when budget is overrun

Two metrics are reported (SHA-144):
  - "sum of means": per-module import micro-benchmark (sum of each module's
    mean import time; excludes shared interpreter overhead). Budget:
    IMPORT_BUDGET_MS (default 600 ms).
  - "wall-clock": end-to-end cold-start SLO (what the user perceives when
    importing every module in sequence). Budget: IMPORT_WALL_BUDGET_MS
    (default 2000 ms).

`--check` enforces BOTH budgets. `--check` alone is *advisory*: it prints a
GitHub Actions `::warning::` line per exceeded budget and exits 0 so CI stays
green. `--hard-fail` flips any overrun into exit 1; reserved for v1.2+ when
the team is ready to enforce the budget hard.

Why soft budgets? Bench numbers depend on hardware (a slow CI runner can blow
a tight threshold without anything regressing in code). Generous defaults +
warn-only mode let us track drift without breaking unrelated PRs. Tighten by
lowering the env vars, or graduate to --hard-fail once the floor is stable.

This script must stay free of allspark.* imports until *inside* the
benchmark loop — otherwise the first measurement is contaminated.
"""
import argparse
import os
import statistics
import sys
import time

MODULES = [
    "allspark.core.config",
    "allspark.core.models",
    "allspark.core.i18n",
    "allspark.core.database",
    "allspark.services.rule_engine",
    "allspark.container",
    "allspark.bootstrap",
    "allspark.services.resource_manager",
    "allspark.services.goal_engine",
    "allspark.services.governance",
    "allspark.services.trade_engine",
    "allspark.services.spark_network",
    "allspark.services.personality",
    "allspark.services.psychology",
    "allspark.services.weather",
    "allspark.services.gps_manager",
    "allspark.services.timeline",
    "allspark.services.diary",
    "allspark.services.daily_briefing",
    "allspark.services.environment",
    "allspark.services.vision_engine",
    "allspark.services.knowledge_engine",
    "allspark.services.skf_manager",
    "allspark.services.sensor_hub",
    "allspark.services.power_monitor",
    "allspark.adapters.cli",
    "allspark.adapters.web_ui",
]

WARMUP = 1
RUNS = 3
DEFAULT_BUDGET_MS = 600.0
DEFAULT_WALL_BUDGET_MS = 2000.0


def benchmark_import(module_name: str) -> dict:
    times = []
    for _ in range(WARMUP + RUNS):
        if module_name in sys.modules:
            del sys.modules[module_name]
        to_remove = [k for k in sys.modules if k.startswith(module_name + ".")]
        for k in to_remove:
            del sys.modules[k]

        start = time.perf_counter()
        try:
            __import__(module_name)
            elapsed = time.perf_counter() - start
            times.append(elapsed)
        except Exception as e:
            return {"module": module_name, "error": str(e)}

    times = times[WARMUP:]
    return {
        "module": module_name,
        "mean_ms": statistics.mean(times) * 1000,
        "min_ms": min(times) * 1000,
        "max_ms": max(times) * 1000,
        "stdev_ms": statistics.stdev(times) * 1000 if len(times) > 1 else 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="AllSpark module import benchmark")
    parser.add_argument(
        "--check", action="store_true",
        help="enforce IMPORT_BUDGET_MS as a soft ceiling on total import time",
    )
    parser.add_argument(
        "--hard-fail", action="store_true",
        help="with --check, exit 1 instead of warn-only when budget is overrun",
    )
    args = parser.parse_args()

    budget_ms = float(os.environ.get("IMPORT_BUDGET_MS", DEFAULT_BUDGET_MS))

    import allspark  # noqa: F401  pre-load package once
    to_remove = [k for k in list(sys.modules) if k.startswith("allspark.")]
    for k in to_remove:
        del sys.modules[k]

    print(f"{'Module':<45} {'Mean(ms)':>10} {'Min(ms)':>10} {'Max(ms)':>10}")
    print("━" * 80)

    results = []
    total_start = time.perf_counter()

    for mod in MODULES:
        r = benchmark_import(mod)
        if "error" in r:
            print(f"{mod:<45} ERROR: {r['error']}")
        else:
            results.append(r)
            print(f"{mod:<45} {r['mean_ms']:>10.2f} {r['min_ms']:>10.2f} {r['max_ms']:>10.2f}")

    total_elapsed = time.perf_counter() - total_start

    print("━" * 80)
    if not results:
        print("No successful imports — nothing to check.")
        return 1 if args.check and args.hard_fail else 0

    total_mean = sum(r["mean_ms"] for r in results)
    slowest = max(results, key=lambda r: r["mean_ms"])
    wall_ms = total_elapsed * 1000
    # SHA-144: report two distinct metrics - per-module micro-benchmark vs
    # end-to-end cold-start SLO. The old check compared only the sum-of-means
    # (which excludes interpreter/environment overhead) against the budget, so
    # a 1567ms wall-clock cold start still passed a 600ms "Within budget".
    print(f"Module import micro-benchmark (sum of means): {total_mean:.1f}ms")
    print(f"Slowest module: {slowest['module']} ({slowest['mean_ms']:.2f}ms)")
    print(f"Cold-start wall-clock SLO: {wall_ms:.1f}ms")

    if not args.check:
        return 0

    wall_budget_ms = float(os.environ.get("IMPORT_WALL_BUDGET_MS", DEFAULT_WALL_BUDGET_MS))
    print(f"Budgets: sum-of-means {budget_ms:.0f}ms (IMPORT_BUDGET_MS), "
          f"wall-clock {wall_budget_ms:.0f}ms (IMPORT_WALL_BUDGET_MS)")
    exceeded = []
    if total_mean > budget_ms:
        exceeded.append(
            f"sum-of-means {total_mean:.1f}ms > {budget_ms:.0f}ms "
            f"(slowest={slowest['module']} {slowest['mean_ms']:.2f}ms)"
        )
    if wall_ms > wall_budget_ms:
        exceeded.append(f"wall-clock {wall_ms:.1f}ms > {wall_budget_ms:.0f}ms")
    if exceeded:
        for msg in exceeded:
            # GitHub Actions consumes ::warning:: lines and surfaces them on the run.
            print(f"::warning::import budget exceeded: {msg}")
        return 1 if args.hard_fail else 0
    print(f"Within budgets (sum-of-means {total_mean:.1f}ms, wall-clock {wall_ms:.1f}ms).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
