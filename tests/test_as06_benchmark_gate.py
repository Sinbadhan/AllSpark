"""Import gates cannot go green after incomplete or invalid measurements."""
import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("modules", [[], ["module_that_does_not_exist"], ["math", "module_that_does_not_exist"]])
@pytest.mark.parametrize("flags", [[], ["--check"], ["--check", "--hard-fail"]])
def test_empty_or_partial_measurements_fail_even_in_advisory_mode(modules, flags):
    code = ("from scripts import bench_import as b; import sys; "
            f"b.MODULES={modules!r}; sys.argv=['bench',*{flags!r}]; sys.exit(b.main())")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    assert result.returncode != 0, result.stdout


@pytest.mark.parametrize("key", ["IMPORT_BUDGET_MS", "IMPORT_WALL_BUDGET_MS"])
@pytest.mark.parametrize("value", ["NaN", "inf", "-1", "0", "bad"])
def test_invalid_budget_cannot_disable_enforcement(key, value):
    result = subprocess.run([sys.executable, "scripts/bench_import.py", "--check", "--hard-fail"],
                            capture_output=True, text=True, timeout=30, env={**os.environ, key: value})
    assert result.returncode != 0, result.stdout
    assert "invalid budget" in result.stderr.lower(), result.stderr


def test_zero_runs_are_an_explicit_configuration_failure():
    code = "from scripts import bench_import as b; import sys; b.RUNS=0; sys.exit(b.main())"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert "measurement configuration" in result.stderr.lower()
