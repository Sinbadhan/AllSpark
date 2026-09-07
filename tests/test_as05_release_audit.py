import pytest

from scripts.verify_release_dependencies import check_audit_report


@pytest.mark.parametrize("rows", [
    [], [{"name": "setuptools", "version": "84.0.0"}],
    [{"name": "setuptools", "version": "84.0.0", "skip_reason": "network unavailable", "vulns": []}],
    [{"name": "setuptools", "version": "58.1.0", "vulns": []}],
    [{"name": "setuptools", "version": "84.0.0", "vulns": [{"id": "TEST-VULNERABILITY"}]}],
    [{"name": "setuptools", "version": "84.0.0", "vulns": []}] * 2,
])
def test_incomplete_or_vulnerable_scans_never_count_as_zero_vulnerabilities(rows):
    with pytest.raises(ValueError):
        check_audit_report({"dependencies": rows}, {"setuptools": "84.0.0"})


def test_exact_complete_scan_is_accepted():
    check_audit_report({"dependencies": [{"name": "setuptools", "version": "84.0.0", "vulns": []}]},
                       {"setuptools": "84.0.0"})
