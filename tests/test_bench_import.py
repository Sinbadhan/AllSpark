"""SHA-144: bench_import reports both metrics and enforces both budgets.

The script must distinguish the per-module micro-benchmark (sum of means) from
the end-to-end cold-start wall-clock SLO, and --hard-fail must exit 1 when
either budget is exceeded (advisory --check stays green).
"""
import os
import subprocess
import sys
from pathlib import Path

BENCH = Path("scripts/bench_import.py")


def _run(*args: str, **env: str) -> subprocess.CompletedProcess:
    full_env = {**os.environ, **env}
    return subprocess.run(
        [sys.executable, str(BENCH), *args],
        capture_output=True, text=True, env=full_env, timeout=120,
    )


class TestBenchImport:
    def test_reports_both_metrics(self):
        r = _run("--check")
        assert r.returncode == 0, r.stderr
        out = r.stdout.lower()
        assert "sum of means" in out or "micro-benchmark" in out
        assert "wall-clock" in out
        assert "budgets:" in out

    def test_hard_fail_exits_1_on_wall_overrun(self):
        r = _run("--check", "--hard-fail", IMPORT_WALL_BUDGET_MS="1")
        assert r.returncode == 1, r.stdout
        assert "wall-clock" in r.stdout.lower()
        assert "::warning::" in r.stdout

    def test_advisory_stays_green_on_overrun(self):
        r = _run("--check", IMPORT_WALL_BUDGET_MS="1")
        assert r.returncode == 0, r.stdout
        assert "::warning::" in r.stdout
