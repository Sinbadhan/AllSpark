#!/usr/bin/env python3
"""SHA-151: per-module branch coverage gate for critical-path modules.

Enforces the total LINE coverage acceptance and a ratcheted BRANCH coverage
floor on each critical-path module from one coverage.py JSON report. Keeping
the two metrics separate avoids coverage.py's combined statement/branch
percentage when branch measurement is enabled.

Release acceptance (Linear SHA-151) requires >=90% branch on the critical
path (auth/init/SKF/import/reset/backup/search/resource) and >=75% total
line coverage. The 9 critical-path floors are pinned to the 90% acceptance
threshold. Other high-risk floors are ratcheted to measured levels to prevent
regression.

Usage:
    # Read a coverage.json produced by the CI pytest step (no pytest re-run):
    python3 scripts/check_coverage.py --coverage-json coverage.json

    # Run pytest + coverage ourselves (checks pytest's exit code first):
    python3 scripts/check_coverage.py

    # Machine-readable JSON output:
    python3 scripts/check_coverage.py --coverage-json coverage.json --json
"""
import argparse
import json
import subprocess
import sys
from typing import Any

# Critical-path modules per SHA-151 acceptance plus other high-risk
# low-coverage modules. Floors are BRANCH coverage %. All 9 critical-path
# modules now meet the >=90% acceptance (Phase B, 2026-07-13, branch
# sha-151/coverage-gate-real); their floor is pinned at 90 so they cannot
# regress below acceptance. Non-critical high-risk modules keep a ratcheted
# floor at their measured level. Raise as targeted tests land; never lower
# without explicit re-scoping of the SHA-151 acceptance.
DEFAULT_BRANCH_FLOORS = {
    # --- critical path (acceptance met: >=90% branch, floor pinned at 90) ---
    "allspark/adapters/init_wizard.py": 90,            # init (17.4% -> 95.7%)
    "allspark/adapters/web_ui.py": 90,                 # auth (48.5% -> 94.1%)
    "allspark/services/skf_manager.py": 90,            # SKF (48.9% -> 100%)
    "allspark/services/knowledge_loader.py": 90,       # import (91.7% -> 100%)
    "allspark/services/reset_manager.py": 90,          # reset (88.9% -> 94.4%)
    "allspark/infrastructure/data_preservation.py": 90,  # backup (36.2% -> 93.1%)
    "allspark/services/knowledge_engine.py": 90,       # search (58.3% -> 94.4%)
    "allspark/services/resource_manager.py": 90,       # resource (68.4% -> 96.9%)
    "allspark/services/initial_assessment.py": 90,      # first-run safety contract
    # --- other high-risk low-coverage modules (ratcheted, non-acceptance) ---
    "allspark/adapters/routes/governance.py": 92,      # (0% -> 92.1%)
    "allspark/commands/survival.py": 9,
    "allspark/commands/docker.py": 8,
    "allspark/services/llm_engine.py": 3,
    "allspark/services/sensor_hub.py": 2,
    "allspark/services/trade_engine.py": 95,           # (3.7% -> 100%)
}

ACCEPTANCE_BRANCH = 90.0      # SHA-151: critical-path branch target
ACCEPTANCE_TOTAL_LINE = 75.0  # SHA-151: total line target


def _run_pytest_with_coverage() -> tuple[int, str]:
    """Run pytest with branch coverage; return (returncode, json_path)."""
    json_path = "/tmp/sha151_cov_gate.json"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "--cov=allspark",
         "--cov-branch", f"--cov-report=json:{json_path}", "--no-header"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # Do NOT mask pytest failures: if tests fail, the gate fails too.
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        sys.stderr.write(
            f"\npytest exited {result.returncode}; coverage gate not evaluated.\n"
        )
    return result.returncode, json_path


def _load_coverage(json_path: str) -> dict[str, Any] | None:
    try:
        with open(json_path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _module_summary(cov: dict[str, Any], module: str) -> dict[str, Any]:
    return cov.get("files", {}).get(module, {}).get("summary", {})


def _branch_pct(summary: dict[str, Any]) -> float:
    if "percent_branches_covered" in summary:
        return float(summary["percent_branches_covered"] or 0)
    nb = summary.get("num_branches", 0)
    if not nb:
        return 0.0
    return 100.0 * summary.get("covered_branches", 0) / nb


def _line_pct(summary: dict[str, Any]) -> float:
    if "percent_statements_covered" in summary:
        return float(summary["percent_statements_covered"] or 0)
    ns = summary.get("num_statements", 0)
    if not ns:
        return 0.0
    return 100.0 * summary.get("covered_lines", 0) / ns


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Per-module branch coverage gate (SHA-151)"
    )
    parser.add_argument(
        "--coverage-json",
        default=None,
        help="path to a coverage.json produced by pytest --cov-report=json; "
        "if omitted, runs pytest + coverage (and checks its exit code)",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable JSON output")
    args = parser.parse_args()

    # Obtain coverage data.
    if args.coverage_json:
        cov = _load_coverage(args.coverage_json)
        if cov is None:
            print(f"ERROR: could not read coverage JSON at {args.coverage_json}")
            return 1
    else:
        rc, json_path = _run_pytest_with_coverage()
        if rc != 0:
            return rc
        cov = _load_coverage(json_path)
        if cov is None:
            print("ERROR: pytest passed but coverage JSON was not produced")
            return 1

    totals = cov.get("totals", {})
    total_line = round(totals.get("percent_statements_covered", 0) or 0, 2)
    total_branch = round(totals.get("percent_branches_covered", 0) or 0, 2)

    rows: list[dict[str, Any]] = []
    failed: list[tuple[str, float, int]] = []
    for module, floor in sorted(DEFAULT_BRANCH_FLOORS.items()):
        s = _module_summary(cov, module)
        line_pct = round(_line_pct(s), 1)
        branch_pct = round(_branch_pct(s), 1)
        nb = s.get("num_branches", 0)
        cb = s.get("covered_branches", 0)
        ok = branch_pct >= floor
        if not ok:
            failed.append((module, branch_pct, floor))
        rows.append({
            "module": module,
            "line": line_pct,
            "branch": branch_pct,
            "floor": floor,
            "covered_branches": cb,
            "num_branches": nb,
            "ok": ok,
            "gap_to_90": round(max(0.0, ACCEPTANCE_BRANCH - branch_pct), 1),
        })

    total_line_gap = round(max(0.0, ACCEPTANCE_TOTAL_LINE - total_line), 2)
    total_line_ok = total_line >= ACCEPTANCE_TOTAL_LINE

    if args.json:
        json.dump({
            "total_line": total_line,
            "total_branch": total_branch,
            "total_line_gap_to_75": total_line_gap,
            "total_line_ok": total_line_ok,
            "acceptance_branch": ACCEPTANCE_BRANCH,
            "acceptance_total_line": ACCEPTANCE_TOTAL_LINE,
            "modules": rows,
            "failed": [{"module": m, "branch": p, "floor": f} for m, p, f in failed],
        }, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"Total line coverage:   {total_line}%  "
              f"(acceptance {ACCEPTANCE_TOTAL_LINE}%, gap {total_line_gap})")
        print(f"Total branch coverage: {total_branch}%")
        print()
        print(f"{'module':<48} {'line%':>6} {'br%':>6} {'floor':>6} {'cov/br':>9} {'gap90':>6}")
        for r in rows:
            mark = "OK " if r["ok"] else "LOW"
            cov_br = f"{r['covered_branches']}/{r['num_branches']}"
            print(f"{mark} {r['module']:<44} {r['line']:>6} {r['branch']:>6} "
                  f"{r['floor']:>6} {cov_br:>9} {r['gap_to_90']:>6}")
        print()
        print("Acceptance gap (SHA-151: >=90% branch critical path, >=75% total line):")
        for r in rows:
            if r["gap_to_90"] > 0:
                print(f"   {r['module']}: {r['branch']}% -> need +{r['gap_to_90']}pp to reach 90%")
        if not total_line_ok:
            print(
                f"\n!! Total line coverage below acceptance: "
                f"{total_line}% < {ACCEPTANCE_TOTAL_LINE}%"
            )
        if failed:
            print(f"\n!! {len(failed)} module(s) below ratcheted floor:")
            for mod, pct, floor in failed:
                print(f"   {mod}: {pct}% < {floor}% floor")
        if total_line_ok and not failed:
            print("\nTotal line coverage and all module branch floors passed.")

    return 1 if failed or not total_line_ok else 0


if __name__ == "__main__":
    sys.exit(main())
