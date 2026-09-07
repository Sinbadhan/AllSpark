# Performance Benchmarks

> **Status:** local CI definition updated on 2026-09-07 (AS-06) to enforce
> both budgets with `--check --hard-fail`. Remote enforcement requires the
> authorized exact-candidate CI run; historical measurements below are not a rerun.
> **Purpose:** track import time so structural regressions surface in
> review rather than after release.

## 1. Import-time baseline (2026-06-13)

Measured by `scripts/bench_import.py` on macOS Darwin 25.5 / Python 3.10
(local laptop, cold caches, 1 warmup + 3 runs per module).

| Module                                  | Mean (ms) | Min (ms) | Max (ms) |
|-----------------------------------------|----------:|---------:|---------:|
| `allspark.core.config`                  |      0.09 |     0.07 |     0.12 |
| `allspark.core.models`                  |      3.20 |     3.11 |     3.33 |
| `allspark.core.i18n`                    |    149.73 |    91.60 |   210.88 |
| `allspark.core.database`                |      0.20 |     0.14 |     0.27 |
| `allspark.services.rule_engine`         |      0.13 |     0.09 |     0.18 |
| `allspark.container`                    |      0.13 |     0.07 |     0.25 |
| `allspark.bootstrap`                    |      0.11 |     0.08 |     0.15 |
| `allspark.services.resource_manager`    |      0.21 |     0.16 |     0.24 |
| `allspark.services.goal_engine`         |      0.11 |     0.09 |     0.13 |
| `allspark.services.governance`          |      0.09 |     0.08 |     0.11 |
| `allspark.services.trade_engine`        |      0.08 |     0.07 |     0.09 |
| `allspark.services.spark_network`       |      0.61 |     0.55 |     0.68 |
| `allspark.services.personality`         |      0.25 |     0.09 |     0.42 |
| `allspark.services.psychology`          |      0.11 |     0.08 |     0.14 |
| `allspark.services.weather`             |      0.08 |     0.06 |     0.10 |
| `allspark.services.gps_manager`         |      0.23 |     0.07 |     0.56 |
| `allspark.services.timeline`            |      0.07 |     0.06 |     0.07 |
| `allspark.services.diary`               |      0.07 |     0.06 |     0.09 |
| `allspark.services.daily_briefing`      |      0.14 |     0.09 |     0.20 |
| `allspark.services.environment`         |      0.08 |     0.07 |     0.10 |
| `allspark.services.vision_engine`       |      0.64 |     0.34 |     0.93 |
| `allspark.services.knowledge_engine`    |      0.25 |     0.21 |     0.31 |
| `allspark.services.skf_manager`         |      0.24 |     0.12 |     0.38 |
| `allspark.services.sensor_hub`          |      1.34 |     0.71 |     1.95 |
| `allspark.services.power_monitor`       |      0.50 |     0.41 |     0.57 |
| `allspark.adapters.cli`                 |      0.12 |     0.07 |     0.19 |
| `allspark.adapters.web_ui`              |      0.14 |     0.10 |     0.20 |
| **Total (sum of means)**                | **158.9** |          |          |
| **Wall-clock total**                    | **901.4** |          |          |
| Slowest module                          | `core.i18n` 149.73ms — dominated by YAML locale parse |

Cold `import allspark` measured separately: ~256 ms wall-clock; the
`bootstrap` symbol then re-exports add ~10 ms.

## 2. Convention

When opening a PR that touches import-time critical paths
(`allspark/__init__.py`, `bootstrap.py`, `container.py`, `core/i18n.py`,
or anything they pull in transitively):

1. Run `python3 scripts/bench_import.py` before and after the change.
2. If any module's mean time grows by **more than 30%**, or the
   sum-of-means grows by more than 30%, call it out in the PR
   description with the new numbers.
3. Update §1 of this file when the change is intentional and lands.

CI runs `python scripts/bench_import.py --check --hard-fail` on every PR.
The budgets are **600 ms** sum-of-means and **2000 ms** cold wall-clock.
Either overrun exits nonzero. Missing imports, zero valid measurements,
non-finite/nonpositive budgets and invalid run counts always fail, even in
advisory mode. `--check` without `--hard-fail` is only an explicitly advisory
local diagnostic and cannot serve as release acceptance.

## 3. Out of scope

- Service runtime performance (rule-engine evaluation, vector search,
  LLM latency). Track those separately when benchmark fixtures exist.
- Web request latency. The current FastAPI surface is small enough to
  measure ad-hoc; revisit when load patterns are known.
