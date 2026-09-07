"""Convert a successful pip installation report into platform-specific hash locks.

Resolution stays in pip. These are artifact locks, not a universal dependency
solver; regenerate and review them for a different platform/Python minor.
"""
import argparse
import json
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def write_locks(report: dict, output: Path) -> None:
    environment = report["environment"]
    if (environment["python_version"], environment["sys_platform"], environment["platform_machine"]) != ("3.12", "darwin", "arm64"):
        raise ValueError("this release target requires macOS arm64 / Python 3.12")
    packages = {canonicalize_name(item["metadata"]["name"]): item for item in report["install"]}
    project = packages["allspark"]
    runtime: set[str] = set()
    queue = [(value, "") for value in project["metadata"]["requires_dist"]]
    visited = set()
    while queue:
        value, extra = queue.pop()
        requirement = Requirement(value)
        if requirement.marker and not requirement.marker.evaluate({**environment, "extra": extra}):
            continue
        name = canonicalize_name(requirement.name)
        item = packages[name]
        runtime.add(name)
        for selected_extra in requirement.extras or {""}:
            if (name, selected_extra) in visited:
                continue
            visited.add((name, selected_extra))
            queue.extend((value, selected_extra) for value in item["metadata"].get("requires_dist", []))
    output.mkdir(parents=True, exist_ok=True)
    for group, selected in (("runtime", runtime), ("release", set(packages) - {"allspark"}), ("bootstrap", {"setuptools"})):
        lines = ["# Generated from pip --dry-run --ignore-installed --report; reviewed 2026-09-07.",
                 "# Target: macOS arm64 / CPython 3.12. Not a lock for other targets.",
                 "# Source registry: https://pypi.org/simple ; each selected artifact is SHA-256 checked."]
        for name in sorted(selected):
            item = packages[name]
            digest = item["download_info"]["archive_info"]["hashes"]["sha256"]
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError(f"missing/invalid artifact digest: {name}")
            lines.append(f"{name}=={item['metadata']['version']} --hash=sha256:{digest}")
        (output / f"{group}-macos-arm64-py312.lock").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, default=Path("requirements"))
    args = parser.parse_args()
    write_locks(json.loads(args.report.read_text()), args.output)
