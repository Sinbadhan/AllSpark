"""SHA-151: tests for the per-module branch coverage gate (scripts/check_coverage.py).

Covers the gate logic itself: below-floor failure, all-above success, missing
JSON, and pytest-failure propagation (the bug that previously let the gate
mask test failures by ignoring pytest's non-zero exit code).
"""
import json
import sys
from pathlib import Path
from typing import Any

import pytest

import scripts.check_coverage as cc  # type: ignore[import-not-found]


def _full_cov(
    *,
    delta: float = 0.0,
    total_line: float = 75.0,
    overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a coverage.py-style JSON dict with every floored module at its floor +/- delta."""
    overrides = overrides or {}
    files: dict[str, Any] = {}
    for mod, floor in cc.DEFAULT_BRANCH_FLOORS.items():
        br = min(100.0, max(0.0, floor + delta))
        summ = {
            "percent_branches_covered": br,
            "num_branches": 100,
            "covered_branches": int(br),
            "percent_statements_covered": br,
            "num_statements": 100,
            "covered_lines": int(br),
        }
        summ.update(overrides.get(mod, {}))
        files[mod] = {"summary": summ}
    return {
        "totals": {
            "percent_statements_covered": total_line,
            "percent_branches_covered": 50.0,
        },
        "files": files,
    }


def _write_cov(tmp_path: Path, cov: dict[str, Any]) -> Path:
    p = tmp_path / "coverage.json"
    p.write_text(json.dumps(cov))
    return p


def _run_main_with_json(cov_path: Path) -> int:
    sys.argv = ["check_coverage.py", "--coverage-json", str(cov_path)]
    return cc.main()


def test_gate_passes_when_all_modules_at_floor(tmp_path: Path) -> None:
    # Every module exactly at its ratcheted floor -> exit 0.
    cov_path = _write_cov(tmp_path, _full_cov(delta=0.0))
    assert _run_main_with_json(cov_path) == 0


def test_gate_fails_when_a_module_below_floor(tmp_path: Path) -> None:
    # init_wizard floor is 90; push it below acceptance -> exit 1.
    cov_path = _write_cov(
        tmp_path,
        _full_cov(overrides={"allspark/adapters/init_wizard.py": {"percent_branches_covered": 89.0}}),
    )
    assert _run_main_with_json(cov_path) == 1


def test_gate_passes_when_modules_above_floor(tmp_path: Path) -> None:
    cov_path = _write_cov(tmp_path, _full_cov(delta=5.0))
    assert _run_main_with_json(cov_path) == 0


def test_gate_fails_when_total_line_below_acceptance(tmp_path: Path) -> None:
    cov_path = _write_cov(tmp_path, _full_cov(total_line=74.99))
    assert _run_main_with_json(cov_path) == 1


def test_gate_passes_when_total_line_at_acceptance(tmp_path: Path) -> None:
    cov_path = _write_cov(tmp_path, _full_cov(total_line=75.0))
    assert _run_main_with_json(cov_path) == 0


def test_gate_fails_on_missing_json(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.json"
    sys.argv = ["check_coverage.py", "--coverage-json", str(missing)]
    assert cc.main() == 1


def test_gate_propagates_pytest_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """If pytest fails, the gate must fail too (regression test for the
    bug where subprocess.run's returncode was ignored)."""
    def _fake_run() -> tuple[int, str]:
        return (1, "/tmp/sha151_cov_gate.json")

    monkeypatch.setattr(cc, "_run_pytest_with_coverage", _fake_run)
    # No --coverage-json: main() must run pytest (faked) and propagate rc=1.
    sys.argv = ["check_coverage.py"]
    assert cc.main() == 1


def test_gate_json_output_is_valid(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cov_path = _write_cov(tmp_path, _full_cov(delta=0.0))
    sys.argv = ["check_coverage.py", "--coverage-json", str(cov_path), "--json"]
    rc = cc.main()
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert "total_line" in payload
    assert payload["total_line_ok"] is True
    assert "modules" in payload
    assert len(payload["modules"]) == len(cc.DEFAULT_BRANCH_FLOORS)
    assert payload["acceptance_branch"] == 90.0
