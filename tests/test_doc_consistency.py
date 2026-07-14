"""SHA-143: executable guards for version, CI, and release-document truth."""

import re
import subprocess
from pathlib import Path

from scripts.check_coverage import ACCEPTANCE_TOTAL_LINE, DEFAULT_BRANCH_FLOORS

STALE_TOKENS = [
    "612 passed",
    "616 passed",
    "614 passed",
    "blocked_by_sandbox",
    "tests/bench_import.py",
    "Do not bump from `0.7.0` to `1.0.0`",
    "tests/` tree is gitignored",
    "tree is gitignored",
    "does **not** run `pytest`",
    "kept private (gitignored",
    "公开发布时保持内部隐藏",
    "内部文档、测试、运行时数据",
]

# Historical changelog sections may retain the numbers that were true then.
EXCLUDE = {"CHANGELOG.md"}


def _tracked_docs() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "*.md"], capture_output=True, text=True, check=True
    )
    return [Path(path) for path in result.stdout.splitlines() if path and path not in EXCLUDE]


def test_tracked_docs_have_no_stale_tokens() -> None:
    docs = _tracked_docs()
    assert docs, "expected tracked .md docs"
    stale = []
    for doc in docs:
        content = doc.read_text(encoding="utf-8")
        for token in STALE_TOKENS:
            if token in content:
                stale.append(f"{doc}: {token!r}")
    assert not stale, "stale claims or paths in tracked docs:\n  " + "\n  ".join(stale)


def test_security_lists_current_version_support() -> None:
    content = Path("SECURITY.md").read_text(encoding="utf-8")
    assert "1.0.x" in content
    assert "| 0.7.x | Yes |" not in content


def test_public_version_references_match() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    package = Path("allspark/__init__.py").read_text(encoding="utf-8")
    version = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE)
    package_version = re.search(r'^__version__ = "([^"]+)"', package, re.MULTILINE)
    assert version is not None and package_version is not None
    assert version.group(1) == package_version.group(1)
    for readme in ("README.md", "README_CN.md"):
        assert f"**v{version.group(1)}**" in Path(readme).read_text(encoding="utf-8")


def test_ci_and_docs_use_current_executable_quality_gates() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "pytest -q --tb=short --cov=allspark --cov-branch" in workflow
    assert "python scripts/check_coverage.py --coverage-json coverage.json" in workflow
    collection_floor = re.search(r'test "\$\{COUNT:-0\}" -ge (\d+)', workflow)
    assert collection_floor is not None and int(collection_floor.group(1)) >= 1129

    critical_modules = {
        "allspark/adapters/init_wizard.py",
        "allspark/adapters/web_ui.py",
        "allspark/services/skf_manager.py",
        "allspark/services/knowledge_loader.py",
        "allspark/services/reset_manager.py",
        "allspark/infrastructure/data_preservation.py",
        "allspark/services/knowledge_engine.py",
        "allspark/services/resource_manager.py",
    }
    assert ACCEPTANCE_TOTAL_LINE == 75.0
    assert all(DEFAULT_BRANCH_FLOORS[module] >= 90 for module in critical_modules)

    docs = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in ("AGENTS.md", "CONTRIBUTING.md", "docs/MANUAL_CHECKLIST.md")
    )
    assert "75%" in docs
    assert "90%" in docs


def test_changelog_unreleased_does_not_overclaim_release_closure() -> None:
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = changelog.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]
    forbidden = (
        "only SHA-33 remains",
        "only real-hardware verification",
        "P0/P1 all cleared",
        "ready for release",
    )
    assert not any(claim in unreleased for claim in forbidden)
    assert "Report-Only" in unreleased
    assert "SHA-213" in unreleased


def test_public_docs_define_honest_release_support_boundary() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_cn = Path("README_CN.md").read_text(encoding="utf-8")
    validation = Path("docs/REAL_WORLD_VALIDATION.md").read_text(encoding="utf-8")

    assert "v1.0.3 Release Support Boundary" in readme
    assert "v1.0.3 发布支持边界" in readme_cn
    for content in (readme, readme_cn, validation):
        assert "PROCESS" in content
        assert "Experimental" in content

    assert "LAN/Bluetooth/WiFi Direct" not in readme
    assert "局域网/蓝牙/WiFi Direct" not in readme_cn
    assert "Bluetooth and Wi-Fi Direct transports" in readme
    assert "蓝牙和 Wi-Fi Direct 传输" in readme_cn
