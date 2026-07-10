"""Tests for scripts/migrate_i18n_legacy.py."""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "migrate_i18n_legacy.py"

# Load the script as a module without installing it, so the test exercises
# the same file CI/users will run.
spec = importlib.util.spec_from_file_location("migrate_i18n_legacy", SCRIPT)
assert spec and spec.loader
migrate_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate_mod)


def _make_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            phase INTEGER NOT NULL DEFAULT 0,
            priority INTEGER NOT NULL DEFAULT 0,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE goals (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            goal_type TEXT DEFAULT 'auto',
            category TEXT DEFAULT 'survival',
            priority TEXT DEFAULT 'medium',
            status TEXT DEFAULT 'active',
            source TEXT DEFAULT 'assessment',
            progress REAL DEFAULT 0.0,
            deadline TEXT DEFAULT '',
            triggers TEXT DEFAULT '[]',
            rationale TEXT DEFAULT '',
            created_by TEXT DEFAULT '',
            milestone_count INTEGER DEFAULT 0,
            milestone_done INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE timeline_events (
            id TEXT PRIMARY KEY,
            day INTEGER NOT NULL DEFAULT 0,
            timestamp TEXT NOT NULL DEFAULT '',
            event_type TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            emotion TEXT DEFAULT 'neutral',
            related_goal_id TEXT DEFAULT '',
            auto_generated INTEGER DEFAULT 1
        );
        """
    )
    return conn


def test_value_to_key_map_skips_format_strings_and_non_strings():
    mapping = migrate_mod.load_value_to_key_map()
    # Sanity: at least one well-known key should round-trip.
    assert "app_name" in mapping.values()
    # No mapping value should still contain placeholder syntax.
    for value in mapping:
        assert "{" not in value


def test_dry_run_does_not_modify(tmp_path: Path):
    db = tmp_path / "spark.db"
    conn = _make_db(db)
    # 火种 is the value for app_name in zh.yaml; pick a row whose title is
    # a known literal so we can predict the rewrite.
    conn.execute("INSERT INTO tasks (id, title) VALUES (?, ?)", ("t1", "火种"))
    conn.commit()
    conn.close()

    counts = migrate_mod.migrate(db, apply=False)
    assert counts["tasks.title"] == 1

    conn = sqlite3.connect(db)
    title = conn.execute("SELECT title FROM tasks WHERE id = 't1'").fetchone()[0]
    assert title == "火种"  # untouched in dry-run
    conn.close()


def test_apply_rewrites_title_and_keeps_unknown_strings(tmp_path: Path):
    db = tmp_path / "spark.db"
    conn = _make_db(db)
    conn.executemany(
        "INSERT INTO tasks (id, title) VALUES (?, ?)",
        [
            ("known-zh", "火种"),                       # → app_name
            ("user-typed", "我自己写的随手记录"),       # not in i18n → keep
        ],
    )
    conn.commit()
    conn.close()

    migrate_mod.migrate(db, apply=True)

    conn = sqlite3.connect(db)
    rows = dict(conn.execute("SELECT id, title FROM tasks").fetchall())
    assert rows["known-zh"] == "app_name"
    assert rows["user-typed"] == "我自己写的随手记录"
    conn.close()


def test_timeline_dedup_drops_zh_en_pair(tmp_path: Path):
    db = tmp_path / "spark.db"
    conn = _make_db(db)
    # Same (day, event_type) but two titles that point at the same key.
    # action_immediate has unique zh ("立即采取行动！") and en ("Take action
    # immediately!") values; both reverse-map to action_immediate.
    conn.executemany(
        "INSERT INTO timeline_events (id, day, event_type, title) VALUES (?, ?, ?, ?)",
        [
            ("ev-zh", 1, "milestone", "立即采取行动！"),
            ("ev-en", 1, "milestone", "Take action immediately!"),
        ],
    )
    conn.commit()
    conn.close()

    migrate_mod.migrate(db, apply=True)

    conn = sqlite3.connect(db)
    remaining = sorted(
        r[0] for r in conn.execute("SELECT id FROM timeline_events").fetchall()
    )
    # Both reverse-map to "action_immediate"; the second insertion (higher
    # rowid) is dropped as a dup of the first.
    assert remaining == ["ev-zh"]
    conn.close()


def test_missing_db_returns_empty_counts(tmp_path: Path):
    counts = migrate_mod.migrate(tmp_path / "nope.db", apply=False)
    assert counts == {}


def test_main_dry_run_with_synthetic_db(tmp_path: Path, capsys: pytest.CaptureFixture):
    db = tmp_path / "spark.db"
    conn = _make_db(db)
    conn.execute("INSERT INTO tasks (id, title) VALUES (?, ?)", ("t1", "火种"))
    conn.commit()
    conn.close()

    rc = migrate_mod.main(["--db", str(db), "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "1 row(s) to rewrite" in out
    assert "dry-run" in out
