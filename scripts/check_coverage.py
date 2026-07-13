#!/usr/bin/env python3
"""SHA-151: per-module coverage gate.

Reports coverage per critical-path module and fails if any fall below their
ratcheted floor. This complements the total `--cov-fail-under` gate in CI by
ensuring low-coverage domains are visible and don't regress.

Usage:
    python3 scripts/check_coverage.py [--fail-under MAP]

The default floors are ratcheted to current levels; raise as tests are added.
"""
import argparse
import json
import subprocess
import sys

# Ratcheted per-module floors (current coverage -> floor).
# Raise these as targeted tests land; never lower without explicit approval.
DEFAULT_FLOORS = {
    "allspark/adapters/init_wizard.py": 20,
    "allspark/adapters/routes/governance.py": 24,
    "allspark/commands/comms.py": 10,
    "allspark/commands/docker.py": 14,
    "allspark/commands/survival.py": 27,
    "allspark/services/llm_engine.py": 32,
    "allspark/services/sensor_hub.py": 33,
    "allspark/services/trade_engine.py": 25,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Per-module coverage gate (SHA-151)")
    parser.add_argument("--json", action="store_true", help="output JSON")
    args = parser.parse_args()

    # Run coverage and parse the JSON report.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "--cov=allspark",
         "--cov-report=json:/tmp/cov_gate.json", "--no-header"],
        capture_output=True, text=True,
    )
    try:
        with open("/tmp/cov_gate.json") as f:
            cov = json.load(f)
    except (OSError, json.JSONDecodeError):
        print("ERROR: could not read coverage JSON")
        return 1

    files = cov.get("files", {})
    failed = []
    for module, floor in sorted(DEFAULT_FLOORS.items()):
        info = files.get(module, {})
        pct = round(info.get("percent_covered", 0), 1)
        status = "OK" if pct >= floor else "BELOW"
        if pct < floor:
            failed.append((module, pct, floor))
        if not args.json:
            print(f"  {status:5} {module:<50} {pct:>5.1f}%  (floor {floor}%)")

    if failed:
        print(f"\n!! {len(failed)} module(s) below floor:")
        for mod, pct, floor in failed:
            print(f"   {mod}: {pct}% < {floor}%")
        return 1
    if not args.json:
        print("\nAll modules at or above floor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
