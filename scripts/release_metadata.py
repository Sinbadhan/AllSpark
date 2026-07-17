#!/usr/bin/env python3
"""Generate deterministic SBOM and third-party license metadata for a release."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import shutil
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
SBOM_NAME = "allspark.cdx.json"
NOTICES_NAME = "THIRD_PARTY_NOTICES.md"
LICENSE_DIR = "third-party-licenses"


def _canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _project_data(root: Path) -> dict[str, Any]:
    try:
        import tomllib
    except ImportError:  # pragma: no cover - Python 3.10
        import tomli as tomllib  # type: ignore[no-redef]
    with (root / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]


def _requirements(project: dict[str, Any], groups: Iterable[str]) -> list[str]:
    values: list[str] = []
    optional = project.get("optional-dependencies", {})
    for group in groups:
        if group == "runtime":
            values.extend(project.get("dependencies", []))
        else:
            if group not in optional:
                raise ValueError(f"unknown dependency group: {group}")
            values.extend(optional[group])
    return values


def _requirement(value: str):
    try:
        from packaging.requirements import Requirement
    except ImportError as exc:  # pragma: no cover - delivery dependency provides it
        raise RuntimeError("release metadata generation requires packaging") from exc
    return Requirement(value)


def _dependency_closure(requirements: Iterable[str]) -> tuple[dict[str, Any], dict[str, set[str]]]:
    distributions: dict[str, Any] = {}
    dependencies: dict[str, set[str]] = {}
    queue: list[tuple[str, str]] = []
    for value in requirements:
        requirement = _requirement(value)
        if requirement.marker is None or requirement.marker.evaluate():
            queue.append((requirement.name, "allspark"))

    while queue:
        requested_name, parent = queue.pop(0)
        canonical = _canonical_name(requested_name)
        dependencies.setdefault(parent, set()).add(canonical)
        if canonical in distributions:
            continue
        try:
            distribution = importlib.metadata.distribution(requested_name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise RuntimeError(f"release dependency is not installed: {requested_name}") from exc
        distributions[canonical] = distribution
        dependencies.setdefault(canonical, set())
        for value in distribution.requires or []:
            requirement = _requirement(value)
            if requirement.marker is None or requirement.marker.evaluate():
                queue.append((requirement.name, canonical))
    return distributions, dependencies


def _license_name(distribution: Any) -> str:
    metadata = distribution.metadata
    expression = metadata.get("License-Expression")
    if expression:
        return expression.strip()
    license_value = metadata.get("License")
    if license_value and len(license_value.strip()) <= 160:
        return license_value.strip()
    classifiers = metadata.get_all("Classifier") or []
    licenses = [item.rsplit(" :: ", 1)[-1] for item in classifiers if item.startswith("License ::")]
    return ", ".join(sorted(set(licenses))) or "UNKNOWN"


def _homepage(distribution: Any) -> str:
    metadata = distribution.metadata
    urls = metadata.get_all("Project-URL") or []
    for preferred in ("Homepage", "Repository", "Source"):
        for value in urls:
            label, separator, url = value.partition(",")
            if separator and label.strip().lower() == preferred.lower():
                return url.strip()
    return (metadata.get("Home-page") or "").strip()


def _safe_segment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "unknown"


def _copy_license_files(distribution: Any, destination: Path) -> list[str]:
    copied: list[str] = []
    name = _safe_segment(distribution.metadata.get("Name") or "unknown")
    version = _safe_segment(distribution.version)
    package_dir = destination / LICENSE_DIR / f"{name}-{version}"
    candidates = []
    for item in distribution.files or []:
        basename = Path(str(item)).name.lower()
        if basename.startswith(("license", "copying", "notice", "copyright")):
            candidates.append(item)
    for item in sorted(candidates, key=str):
        source = Path(distribution.locate_file(item))
        if not source.is_file() or source.stat().st_size > 2 * 1024 * 1024:
            continue
        package_dir.mkdir(parents=True, exist_ok=True)
        target = package_dir / _safe_segment(Path(str(item)).name)
        if target.exists():
            continue
        shutil.copyfile(source, target)
        copied.append(target.relative_to(destination).as_posix())
    return copied


def generate_release_metadata(
    root: Path,
    destination: Path,
    *,
    groups: tuple[str, ...] = ("runtime", "delivery"),
) -> dict[str, Any]:
    project = _project_data(root)
    distributions, dependency_graph = _dependency_closure(_requirements(project, groups))
    destination.mkdir(parents=True, exist_ok=True)
    licenses: dict[str, list[str]] = {}
    components = []
    for canonical, distribution in sorted(distributions.items()):
        name = distribution.metadata.get("Name") or canonical
        license_name = _license_name(distribution)
        license_files = _copy_license_files(distribution, destination)
        licenses[canonical] = license_files
        component: dict[str, Any] = {
            "type": "library",
            "bom-ref": f"pkg:pypi/{canonical}@{distribution.version}",
            "name": name,
            "version": distribution.version,
            "purl": f"pkg:pypi/{canonical}@{distribution.version}",
            "licenses": [{"license": {"name": license_name}}],
            "properties": [
                {"name": "allspark:license-files", "value": ",".join(license_files)},
            ],
        }
        homepage = _homepage(distribution)
        if homepage:
            component["externalReferences"] = [{"type": "website", "url": homepage}]
        components.append(component)

    dependencies = []
    project_ref = f"pkg:pypi/allspark@{project['version']}"
    for parent, children in sorted(dependency_graph.items()):
        ref = project_ref if parent == "allspark" else f"pkg:pypi/{parent}@{distributions[parent].version}"
        dependencies.append(
            {
                "ref": ref,
                "dependsOn": [
                    f"pkg:pypi/{child}@{distributions[child].version}"
                    for child in sorted(children)
                ],
            }
        )
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "bom-ref": project_ref,
                "name": project["name"],
                "version": project["version"],
                "licenses": [{"license": {"id": project.get("license", "Apache-2.0")}}],
            },
            "properties": [
                {"name": "allspark:dependency-groups", "value": ",".join(groups)},
            ],
        },
        "components": components,
        "dependencies": dependencies,
    }
    sbom_path = destination / SBOM_NAME
    sbom_path.write_text(
        json.dumps(bom, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    lines = [
        "# Third-Party Notices",
        "",
        "Generated from the exact installed dependency closure used for this release artifact.",
        "AllSpark itself is licensed under Apache-2.0; see the repository LICENSE file.",
        "",
    ]
    for component in components:
        canonical = _canonical_name(component["name"])
        license_name = component["licenses"][0]["license"]["name"]
        lines.extend([f"## {component['name']} {component['version']}", "", f"License: {license_name}"])
        if component.get("externalReferences"):
            lines.append(f"Project: {component['externalReferences'][0]['url']}")
        for path in licenses[canonical]:
            lines.append(f"License text: `{path}`")
        lines.append("")
    (destination / NOTICES_NAME).write_text("\n".join(lines), encoding="utf-8", newline="\n")

    unknown = [
        component["name"]
        for component in components
        if component["licenses"][0]["license"]["name"] == "UNKNOWN"
    ]
    return {
        "component_count": len(components),
        "unknown_licenses": unknown,
        "sbom_sha256": hashlib.sha256(sbom_path.read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--group", action="append", dest="groups", default=[])
    args = parser.parse_args()
    groups = tuple(args.groups or ["runtime", "delivery"])
    result = generate_release_metadata(ROOT, args.output, groups=groups)
    print(json.dumps(result, sort_keys=True))
    return 1 if result["unknown_licenses"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
