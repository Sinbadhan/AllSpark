#!/usr/bin/env python3
"""Audit SHA-241 scenario fixtures and optionally enforce external review."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from allspark.services.safety_scenario_audit import audit_safety_scenarios


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-reviewed",
        action="store_true",
        help="fail unless every scenario and bundled risk record is externally reviewed",
    )
    args = parser.parse_args()
    report = audit_safety_scenarios()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if args.require_reviewed and report["release_review_gate"]["status"] != "passed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
