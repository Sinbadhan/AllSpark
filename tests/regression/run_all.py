"""Run every regression suite in sequence and write a combined report."""
from __future__ import annotations

import sys
import time
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = "tests.regression"

from tests.regression import suite_boundary, suite_cli, suite_html_render, suite_web_api
from tests.regression._harness import REPORTS_DIR, EnvironmentBlocked

SUITES = [
    ("web_api", suite_web_api.main),
    ("cli", suite_cli.main),
    ("boundary", suite_boundary.main),
    ("html_render", suite_html_render.main),
]


def main() -> int:
    started = time.time()
    rows: list[tuple[str, int, float, str]] = []
    for name, fn in SUITES:
        print(f"\n========== {name} ==========")
        t0 = time.time()
        note = ""
        try:
            rc = fn()
        except EnvironmentBlocked as exc:
            rc = 0
            note = f"environment_blocked: {exc}"
            report = REPORTS_DIR / f"{name}.md"
            report.write_text(
                f"# {name} regression — environment blocked\n\n"
                f"{exc}\n\n"
                "This is not a product failure. Re-run on a host that allows "
                "127.0.0.1 TCP bind to validate this suite.\n",
                encoding="utf-8",
            )
            print(f"{name}: environment blocked ({exc})")
        rows.append((name, rc, time.time() - t0, note))

    total_secs = time.time() - started
    md_lines = [
        f"# AllSpark regression — combined run ({total_secs:.1f}s)",
        "",
        "## Triage verdict (SHA-60)",
        "",
        "This index separates three outcomes so a release gate can tell them apart:",
        "- **Blocking** — real failures: `5xx`, `4xx_unexpected`, `transport_error`,",
        "  `traceback`, `nonzero_rc`, and genuine `i18n_leak` / cross-language flags.",
        "- **Allowed degradation** — `degraded_allowlisted`: an optional service is",
        "  intentionally not loaded in this environment (e.g. spark_network / vision",
        "  without the matching hardware). Each record carries an `allowlist_reason`.",
        "- **Known external dependency unavailable** — recorded but not blocking.",
        "- **Environment blocked** — the host/sandbox forbids a required local",
        "  resource such as 127.0.0.1 TCP bind; rerun on CI or a real local shell.",
        "",
        "If a release shows only `degraded_allowlisted` (no bare `5xx` / `4xx_unexpected`),",
        "the surface is green.",
        "",
        "| suite | rc | seconds | report | note |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, rc, secs, note in rows:
        md_lines.append(
            f"| {name} | {rc} | {secs:.1f} | "
            f"[{name}.md](./{name}.md) | {note} |"
        )
    md_lines.append("")
    md_lines.append("Per-suite JSONL artifacts live alongside the markdown.")
    (REPORTS_DIR / "INDEX.md").write_text("\n".join(md_lines) + "\n")

    print(f"\nIndex: {REPORTS_DIR / 'INDEX.md'}")
    return max(rc for _, rc, _, _ in rows)


if __name__ == "__main__":
    raise SystemExit(main())
