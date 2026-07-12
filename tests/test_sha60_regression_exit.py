"""SHA-60: regression suite exit code must reflect blocking flags.

The regression suites used to unconditionally `return 0`, so a
`transport_error` / non-allowlist 5xx / 4xx would still pass (false green).
blocking_records() now identifies blocking flags; each suite returns non-zero
when any are present. ``degraded_allowlisted`` (expected graceful degradation)
and informational flags do NOT block.
"""
from tests.regression._harness import BLOCKING_FLAGS, CallRecord, blocking_records


class TestBlockingFlags:
    def test_transport_error_is_blocking(self):
        rec = CallRecord(kind="http", label="x", flags=["transport_error"])
        assert blocking_records([rec]) == [rec]

    def test_5xx_is_blocking(self):
        rec = CallRecord(kind="http", label="x", flags=["5xx"])
        assert blocking_records([rec]) == [rec]

    def test_4xx_unexpected_is_blocking(self):
        rec = CallRecord(kind="http", label="x", flags=["4xx_unexpected"])
        assert blocking_records([rec]) == [rec]

    def test_degraded_allowlisted_not_blocking(self):
        rec = CallRecord(kind="http", label="x", flags=["degraded_allowlisted"])
        assert blocking_records([rec]) == []

    def test_boundary_pass_not_blocking(self):
        rec = CallRecord(kind="http", label="x", flags=["boundary_pass"])
        assert blocking_records([rec]) == []

    def test_environment_blocked_not_blocking(self):
        rec = CallRecord(kind="http", label="x", flags=["environment_blocked"])
        assert blocking_records([rec]) == []

    def test_empty(self):
        assert blocking_records([]) == []

    def test_mixed_records_only_blocking_returned(self):
        ok = CallRecord(kind="http", label="ok", flags=["degraded_allowlisted"])
        bad = CallRecord(kind="http", label="bad", flags=["transport_error"])
        assert blocking_records([ok, bad]) == [bad]

    def test_blocking_flags_set_covers_real_regressions(self):
        for f in ("transport_error", "5xx", "4xx_unexpected",
                  "ok_unexpected", "i18n_leak", "json_error"):
            assert f in BLOCKING_FLAGS
        assert "degraded_allowlisted" not in BLOCKING_FLAGS
