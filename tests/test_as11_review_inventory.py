import copy
import re
import subprocess
import sys
from pathlib import Path

from allspark.services.knowledge_loader import load_knowledge
from scripts.knowledge_review_inventory import inventory


def test_complete_bilingual_inventory_does_not_claim_review():
    entries = load_knowledge()
    before = copy.deepcopy(entries)
    report = inventory(entries)
    assert entries == before
    assert (report["topic_count"], report["record_count"]) == (76, 152)
    assert report["inventory_integrity"] == "passed"
    assert report["content_risk_gate"] == "blocked"
    assert report["actionable_count"] == 0
    assert report["gap_counts"]["source_reference_missing"] == 152
    assert report["gap_counts"]["risk_approval_missing"] == 152
    assert len({(row["id"], row["language"]) for row in report["records"]}) == 152
    assert all(re.fullmatch(r"sha256:[a-f0-9]{64}", row["content_hash"]) for row in report["records"])


def test_inventory_rejects_empty_duplicate_and_missing_language():
    entries = load_knowledge()
    for invalid in ([], entries + entries[:1], entries[1:]):
        report = inventory(invalid)
        assert report["inventory_integrity"] == "failed"
        assert report["content_risk_gate"] == "blocked"
    changed = copy.deepcopy(entries)
    changed[0].summary += " Changed statement."
    original = {(row["id"], row["language"]): row for row in inventory(entries)["records"]}
    updated = {(row["id"], row["language"]): row for row in inventory(changed)["records"]}
    key = (changed[0].id, changed[0].language)
    assert original[key]["content_hash"] != updated[key]["content_hash"]


def test_readmes_report_loaded_topics_not_approval_counts():
    report = inventory(load_knowledge())
    for name, language in (("README.md", "en"), ("README_CN.md", "zh")):
        rows = re.findall(r"^\| Tier (\d) \|[^\n]+\| (\d+) \|$", Path(name).read_text(), re.M)
        assert {int(tier): int(count) for tier, count in rows} == report["tier_language_counts"][language]


def test_review_required_mode_fails_for_current_bundled_entries():
    result = subprocess.run(
        [sys.executable, "scripts/knowledge_review_inventory.py", "--require-reviewed"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 1, result.stderr
    assert '"content_risk_gate": "blocked"' in result.stdout
