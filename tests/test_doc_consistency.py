"""SHA-143: document consistency guard.

Asserts tracked docs (the public set CI sees) do not regress to stale test/CI
口径 or deleted paths. Internal gitignored docs (PROGRESS/ARCHITECTURE/etc.)
are not in CI and are excluded; CHANGELOG records historical facts and is also
excluded. When the test count or CI surface changes, update the docs AND the
STALE_TOKENS list deliberately, not silently.
"""
import subprocess
from pathlib import Path

# Tokens that must never reappear in tracked docs (excluding CHANGELOG).
# - stale test counts (612/616/614) replaced by 722 + "以实际输出为准"
# - "blocked_by_sandbox" loopback claim (regression passes exit 0 now)
# - deleted path tests/bench_import.py (lives at scripts/bench_import.py)
# - old 0.7->1.0 bump instruction (project is on 1.0.x)
# - stale claim that tests/ is gitignored (tracked since SHA-28)
STALE_TOKENS = [
    "612 passed",
    "616 passed",
    "614 passed",
    "blocked_by_sandbox",
    "tests/bench_import.py",
    "Do not bump from `0.7.0` to `1.0.0`",
    "tests/` tree is gitignored",
    "tree is gitignored",
]

# Historical records; their old counts are facts at release time, not stale口径.
EXCLUDE = {"CHANGELOG.md"}


def _tracked_docs() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "*.md"], capture_output=True, text=True, check=True
    )
    return [Path(p) for p in result.stdout.splitlines() if p and p not in EXCLUDE]


def test_tracked_docs_have_no_stale_tokens():
    docs = _tracked_docs()
    assert docs, "expected tracked .md docs"
    stale = []
    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        for token in STALE_TOKENS:
            if token in text:
                stale.append(f"{doc}: {token!r}")
    assert not stale, "stale口径/paths in tracked docs:\n  " + "\n  ".join(stale)


def test_security_lists_current_version_support():
    """SECURITY.md must list the 1.0.x line (project is 1.0.3), not just 0.7.x."""
    text = Path("SECURITY.md").read_text(encoding="utf-8")
    assert "1.0.x" in text
    assert "| 0.7.x | Yes |" not in text  # 0.7.x alone (without 1.0.x) is stale
