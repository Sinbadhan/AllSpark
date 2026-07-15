#!/usr/bin/env python3
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from allspark.services.knowledge_audit import audit_bundled_knowledge


def main() -> int:
    logging.disable(logging.CRITICAL)
    result = audit_bundled_knowledge()
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    return 1 if result["violations"] or result["legacy_level_entries"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
