"""Regression suite scaffolding for AllSpark.

Each `suite_*.py` is an executable script. Run a single suite with:

    python -m tests.regression.suite_web_api
    python -m tests.regression.suite_cli
    python -m tests.regression.suite_boundary
    python -m tests.regression.suite_html_render

Or run them all and aggregate:

    python -m tests.regression.run_all

Reports land in `tests/regression/reports/` (gitignored) — one
JSONL per suite plus a combined Markdown summary.

This module is intentionally **not** discovered by pytest.
See `tests/regression/README.md` for the coverage matrix and policy.
"""
