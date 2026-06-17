"""i18n historical-data migration — convert persisted bilingual title strings
back to i18n keys.

Background
----------
Before SHA-7 / B-2 (commit 241a641), services like mission_planner and
goal_engine persisted the *translated* title (e.g. "URGENT: Find safe water
source" or "急需：寻找安全水源") into ``tasks.title`` / ``goals.title`` /
``timeline_events.title``. Once the user switched language, those rows kept
their original-language string forever — UI ended up half-Chinese
half-English.

The code-layer fix (B-2) made *new* writes store i18n keys. This script
retrofits *old* rows by reverse-mapping each persisted string back to its
i18n key via ``locales/zh.yaml`` + ``locales/en.yaml``, and deduplicates
timeline rows that the bug created twice (one per language).

Usage
-----
::

    python scripts/migrate_i18n_legacy.py --dry-run [--db PATH]
    python scripts/migrate_i18n_legacy.py --apply   [--db PATH]

``--dry-run`` (default) reports per-table counts without writing.
``--apply`` performs the migration inside a transaction.

Strings containing user-supplied content (no key match) are left intact —
they belong to user-typed diary/goal text, not framework-generated titles.

The mapping ignores i18n values containing ``{`` placeholders, since those
are formatted at runtime and cannot be safely reverse-mapped from a
finished string.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import yaml

# Allow running from repo root without installing the package.
ROOT = Path(__file__).resolve().parent.parent
LOCALES_DIR = ROOT / "allspark" / "locales"
DEFAULT_DB = Path.home() / ".allspark" / "spark.db"

TABLES = ("tasks", "goals", "timeline_events")  # all use a `title` column


def load_value_to_key_map() -> dict[str, str]:
    """Build {translated_value: i18n_key} from zh.yaml + en.yaml.

    Skips entries whose value contains ``{`` (runtime-formatted strings)
    or that are not plain strings (nested mappings/lists).
    Skips zero-length strings.

    Caveat — when two distinct keys share the same translated value
    (e.g. ``app_name`` and ``web_app_title`` both rendering to
    ``AllSpark`` in en.yaml), the LAST-seen key wins. This is acceptable
    for one-off historical-data cleanup: the rewrite still maps to *some*
    valid i18n key, just not necessarily the one that originally produced
    the persisted string. A full audit would require recording the
    producing key at write-time, which post-B-2 already does.
    """
    mapping: dict[str, str] = {}
    for locale_file in ("zh.yaml", "en.yaml"):
        path = LOCALES_DIR / locale_file
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        for key, val in data.items():
            if not isinstance(val, str) or not val:
                continue
            if "{" in val:
                continue
            mapping[val] = key
    return mapping


def find_legacy_rows(
    conn: sqlite3.Connection,
    table: str,
    mapping: dict[str, str],
) -> list[tuple[str, str, str]]:
    """Return [(id, current_title, target_key), ...] for rows whose title
    is a literal i18n value."""
    cur = conn.execute(f"SELECT id, title FROM {table}")
    out: list[tuple[str, str, str]] = []
    for row_id, title in cur.fetchall():
        if not title:
            continue
        key = mapping.get(title)
        if key is not None and key != title:
            out.append((row_id, title, key))
    return out


def find_timeline_dupes(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Find timeline rows where the same (day, event_type) has two titles
    that map back to the same i18n key (i.e. one Chinese, one English).
    Returns [(id_to_drop, reason)] keeping the older row by ROWID.
    """
    cur = conn.execute(
        "SELECT id, day, event_type, title, rowid FROM timeline_events "
        "ORDER BY day, event_type, rowid"
    )
    seen: dict[tuple[int, str, str], str] = {}
    drops: list[tuple[str, str]] = []
    mapping = load_value_to_key_map()
    for row_id, day, etype, title, _rowid in cur.fetchall():
        key = mapping.get(title, title)
        bucket = (day, etype, key)
        if bucket in seen:
            drops.append((row_id, f"dup of {seen[bucket]} ({day}/{etype}/{key})"))
        else:
            seen[bucket] = row_id
    return drops


def migrate(db_path: Path, *, apply: bool) -> dict[str, int]:
    if not db_path.exists():
        print(f"⚠  database not found: {db_path}", file=sys.stderr)
        return {}

    mapping = load_value_to_key_map()
    print(f"loaded {len(mapping)} (value → key) entries from locales")

    conn = sqlite3.connect(db_path)
    conn.execute("BEGIN")
    counts: dict[str, int] = {}

    try:
        for table in TABLES:
            rows = find_legacy_rows(conn, table, mapping)
            counts[f"{table}.title"] = len(rows)
            print(f"  {table}.title: {len(rows)} row(s) to rewrite")
            if apply and rows:
                conn.executemany(
                    f"UPDATE {table} SET title = ? WHERE id = ?",
                    [(key, row_id) for row_id, _old, key in rows],
                )

        dupes = find_timeline_dupes(conn)
        counts["timeline_events.dupes"] = len(dupes)
        print(f"  timeline_events dupes: {len(dupes)} row(s) to drop")
        if apply and dupes:
            conn.executemany(
                "DELETE FROM timeline_events WHERE id = ?",
                [(row_id,) for row_id, _reason in dupes],
            )

        if apply:
            conn.commit()
            print("✓ committed")
        else:
            conn.rollback()
            print("(dry-run, rolled back)")
    finally:
        conn.close()

    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"sqlite database path (default: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually write the migration (default is dry-run)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="explicit dry-run; default behavior anyway",
    )
    args = parser.parse_args(argv)

    apply = bool(args.apply) and not args.dry_run
    counts = migrate(args.db, apply=apply)

    if not counts:
        return 1
    total = sum(counts.values())
    print(f"\nsummary: {total} row(s) {'rewritten/deleted' if apply else 'would be touched'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
