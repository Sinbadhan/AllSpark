"""Fail-closed audit of hash-locked inputs and independent CycloneDX validation."""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def check_audit_report(report: dict, expected: dict[str, str]) -> None:
    rows = report.get("dependencies", [])
    observed = {canonicalize_name(row["name"]): row.get("version") for row in rows}
    if not expected or observed != expected or len(rows) != len(expected):
        raise ValueError("audit did not cover the exact locked dependency set")
    for row in rows:
        if row.get("skip_reason") or "vulns" not in row or row["vulns"]:
            raise ValueError(f"dependency was skipped, not scanned, or vulnerable: {row['name']}")


def main() -> None:
    from scripts.release_metadata import generate_release_metadata

    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    expected = {}
    for line in args.lock.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        requirement = Requirement(line.split(" --hash=", 1)[0])
        specifiers = list(requirement.specifier)
        if len(specifiers) != 1 or specifiers[0].operator != "==" or " --hash=sha256:" not in line:
            raise ValueError("release audit requires exact artifact-hashed inputs")
        expected[canonicalize_name(requirement.name)] = specifiers[0].version
    audit_path = args.output / "vulnerabilities.json"
    subprocess.run([sys.executable, "-m", "pip_audit", "--require-hashes", "--disable-pip",
                    "-r", str(args.lock), "--format", "json", "--output", str(audit_path)], check=True)
    check_audit_report(json.loads(audit_path.read_text()), expected)
    metadata = generate_release_metadata(ROOT, args.output)
    if metadata["unknown_licenses"]:
        raise ValueError(f"unknown licenses: {metadata['unknown_licenses']}")
    from cyclonedx.schema import SchemaVersion
    from cyclonedx.validation.json import JsonStrictValidator
    validator = JsonStrictValidator(SchemaVersion.V1_5)
    error = validator.validate_str((args.output / "allspark.cdx.json").read_text())
    if error is not None:
        raise ValueError(f"independent CycloneDX schema rejected SBOM: {error}")
    print(json.dumps({"status": "passed", "queried_at": datetime.now(timezone.utc).isoformat(),
                      "scanned_dependencies": len(expected), **metadata}))


if __name__ == "__main__":
    main()
