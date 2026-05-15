import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from allspark.models import (
    Resource, ResourceType, Task, KnowledgeEntry,
    ExperienceLog, MapPOI, OperatingState, OperatingMode
)
from allspark.tokenizer import tokenize, tokenize_query


class Database:
    @staticmethod
    def _row_to_entry(r) -> KnowledgeEntry:
        return KnowledgeEntry(
            id=r["id"], category=r["category"],
            subcategory=r["subcategory"], priority=r["priority"],
            title=r["title"], summary=r["summary"],
            steps=json.loads(r["steps"]),
            prerequisites=json.loads(r["prerequisites"]),
            warnings=json.loads(r["warnings"]),
            verification=r["verification"],
            source=r["source"], version=r["version"],
            language=r["language"] if "language" in r.keys() else "zh"
        )

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            from allspark.config import DEFAULT_DB_PATH
            db_path = DEFAULT_DB_PATH
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        cur = self.conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS resources (
                type TEXT PRIMARY KEY,
                current_amount REAL NOT NULL,
                unit TEXT NOT NULL,
                daily_consumption REAL DEFAULT 0,
                daily_intake REAL DEFAULT 0,
                estimated_remaining_hours REAL DEFAULT 0,
                last_updated TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                phase INTEGER NOT NULL,
                priority INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS knowledge (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                subcategory TEXT NOT NULL,
                priority INTEGER NOT NULL,
                title TEXT NOT NULL,
                summary TEXT DEFAULT '',
                steps TEXT DEFAULT '[]',
                prerequisites TEXT DEFAULT '[]',
                warnings TEXT DEFAULT '[]',
                verification TEXT DEFAULT 'unverified',
                source TEXT DEFAULT 'pre_collapse',
                version INTEGER DEFAULT 1,
                language TEXT DEFAULT 'zh'
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                id, title, summary, steps, category, subcategory
            );

            CREATE TABLE IF NOT EXISTS experience_log (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                event TEXT NOT NULL,
                outcome TEXT NOT NULL,
                lesson TEXT DEFAULT '',
                related_knowledge_id TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS map_pois (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                description TEXT DEFAULT '',
                distance_km REAL DEFAULT 0,
                direction TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                discovered_at TEXT NOT NULL,
                verified INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS operating_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS survivor_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS hardware_profile (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS community_members (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT DEFAULT 'executor',
                domains TEXT DEFAULT '[]',
                skills TEXT DEFAULT '[]',
                health_status TEXT DEFAULT 'unknown',
                psychological_stability REAL DEFAULT 0.5,
                contribution_score REAL DEFAULT 0,
                joined_at TEXT NOT NULL,
                last_active TEXT NOT NULL,
                is_commander INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS conflicts (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                parties TEXT DEFAULT '[]',
                status TEXT DEFAULT 'open',
                mediator TEXT DEFAULT '',
                resolution TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                resolved_at TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS trade_offers (
                id TEXT PRIMARY KEY,
                proposer_id TEXT NOT NULL,
                target_spark_id TEXT NOT NULL,
                offer_knowledge_ids TEXT DEFAULT '[]',
                request_knowledge_ids TEXT DEFAULT '[]',
                status TEXT DEFAULT 'proposed',
                created_at TEXT NOT NULL,
                completed_at TEXT DEFAULT ''
            );
        """)
        self.conn.commit()
        self._migrate()

    def _migrate(self):
        cur = self.conn.cursor()
        try:
            cur.execute("SELECT language FROM knowledge LIMIT 1")
        except sqlite3.OperationalError:
            cur.execute("ALTER TABLE knowledge ADD COLUMN language TEXT DEFAULT 'zh'")
            self.conn.commit()

    def _now(self) -> str:
        return datetime.now().isoformat()

    # --- Resources ---

    def upsert_resource(self, r: Resource):
        self.conn.execute(
            "INSERT OR REPLACE INTO resources VALUES (?,?,?,?,?,?,?)",
            (r.type.value, r.current_amount, r.unit,
             r.daily_consumption, r.daily_intake,
             r.estimated_remaining_hours, self._now())
        )
        self.conn.commit()

    def get_resource(self, rtype: ResourceType) -> Optional[Resource]:
        row = self.conn.execute(
            "SELECT * FROM resources WHERE type=?", (rtype.value,)
        ).fetchone()
        if not row:
            return None
        return Resource(
            type=ResourceType(row["type"]),
            current_amount=row["current_amount"],
            unit=row["unit"],
            daily_consumption=row["daily_consumption"],
            daily_intake=row["daily_intake"],
            estimated_remaining_hours=row["estimated_remaining_hours"],
            last_updated=row["last_updated"]
        )

    def get_all_resources(self) -> list[Resource]:
        rows = self.conn.execute("SELECT * FROM resources").fetchall()
        return [Resource(
            type=ResourceType(r["type"]),
            current_amount=r["current_amount"],
            unit=r["unit"],
            daily_consumption=r["daily_consumption"],
            daily_intake=r["daily_intake"],
            estimated_remaining_hours=r["estimated_remaining_hours"],
            last_updated=r["last_updated"]
        ) for r in rows]

    # --- Tasks ---

    def save_task(self, t: Task):
        self.conn.execute(
            "INSERT OR REPLACE INTO tasks VALUES (?,?,?,?,?,?,?)",
            (t.id, t.phase, t.priority, t.title, t.description,
             t.status, t.created_at, self._now())
        )
        self.conn.commit()

    def get_tasks_by_phase(self, phase: int) -> list[Task]:
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE phase=? ORDER BY priority", (phase,)
        ).fetchall()
        return [Task(**dict(r)) for r in rows]

    def get_active_tasks(self) -> list[Task]:
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE status IN ('pending','in_progress') ORDER BY priority"
        ).fetchall()
        return [Task(**dict(r)) for r in rows]

    def update_task_status(self, task_id: str, status: str):
        self.conn.execute(
            "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
            (status, self._now(), task_id)
        )
        self.conn.commit()

    # --- Knowledge ---

    def save_knowledge(self, k: KnowledgeEntry):
        steps_json = json.dumps(k.steps, ensure_ascii=False)
        prereq_json = json.dumps(k.prerequisites, ensure_ascii=False)
        warn_json = json.dumps(k.warnings, ensure_ascii=False)
        self.conn.execute(
            "INSERT OR REPLACE INTO knowledge VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (k.id, k.category, k.subcategory, k.priority, k.title,
             k.summary, steps_json, prereq_json, warn_json,
             k.verification, k.source, k.version, k.language)
        )
        self.conn.execute(
            "DELETE FROM knowledge_fts WHERE id=?", (k.id,)
        )
        self.conn.execute(
            "INSERT INTO knowledge_fts VALUES (?,?,?,?,?,?)",
            (k.id, tokenize(k.title), tokenize(k.summary),
             tokenize(steps_json), tokenize(k.category),
             tokenize(k.subcategory))
        )
        self.conn.commit()

    def get_knowledge(self, kid: str) -> Optional[KnowledgeEntry]:
        row = self.conn.execute(
            "SELECT * FROM knowledge WHERE id=?", (kid,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_entry(row)

    def search_knowledge(self, query: str, limit: int = 10) -> list[KnowledgeEntry]:
        results = []
        seen_ids = set()
        try:
            fts_query = tokenize_query(query)
            if fts_query:
                rows = self.conn.execute(
                    """SELECT k.* FROM knowledge k
                       WHERE k.id IN (
                           SELECT id FROM knowledge_fts WHERE knowledge_fts MATCH ?
                       )
                       ORDER BY k.priority LIMIT ?""",
                    (fts_query, limit)
                ).fetchall()
                for r in rows:
                    if r["id"] not in seen_ids:
                        seen_ids.add(r["id"])
                        results.append(r)
        except Exception:
            pass

        if len(results) < limit:
            keywords = query.split()
            for kw in keywords:
                like_rows = self.conn.execute(
                    """SELECT * FROM knowledge
                       WHERE title LIKE ? OR summary LIKE ? OR steps LIKE ?
                       OR category LIKE ? OR subcategory LIKE ?
                       ORDER BY priority LIMIT ?""",
                    (f"%{kw}%", f"%{kw}%", f"%{kw}%",
                     f"%{kw}%", f"%{kw}%", limit)
                ).fetchall()
                for r in like_rows:
                    if r["id"] not in seen_ids:
                        seen_ids.add(r["id"])
                        results.append(r)

        entries = []
        for r in results:
            entries.append(self._row_to_entry(r))
        return entries

    def get_knowledge_by_category(self, category: str, subcategory: str = "") -> list[KnowledgeEntry]:
        if subcategory:
            rows = self.conn.execute(
                "SELECT * FROM knowledge WHERE category=? AND subcategory=? ORDER BY priority",
                (category, subcategory)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM knowledge WHERE category=? ORDER BY priority",
                (category,)
            ).fetchall()
        results = []
        for r in rows:
            results.append(self._row_to_entry(r))
        return results

    def get_knowledge_by_priority(self, max_priority: int = 3) -> list[KnowledgeEntry]:
        rows = self.conn.execute(
            "SELECT * FROM knowledge WHERE priority<=? ORDER BY priority, category",
            (max_priority,)
        ).fetchall()
        results = []
        for r in rows:
            results.append(self._row_to_entry(r))
        return results

    # --- Experience Log ---

    def save_experience(self, e: ExperienceLog):
        self.conn.execute(
            "INSERT OR REPLACE INTO experience_log VALUES (?,?,?,?,?,?)",
            (e.id, e.timestamp, e.event, e.outcome, e.lesson, e.related_knowledge_id)
        )
        self.conn.commit()

    def get_recent_experiences(self, limit: int = 20) -> list[ExperienceLog]:
        rows = self.conn.execute(
            "SELECT * FROM experience_log ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [ExperienceLog(**dict(r)) for r in rows]

    # --- Map POIs ---

    def save_poi(self, p: MapPOI):
        self.conn.execute(
            "INSERT OR REPLACE INTO map_pois VALUES (?,?,?,?,?,?,?,?,?)",
            (p.id, p.name, p.type, p.description, p.distance_km,
             p.direction, p.notes, p.discovered_at, 1 if p.verified else 0)
        )
        self.conn.commit()

    def get_all_pois(self) -> list[MapPOI]:
        rows = self.conn.execute("SELECT * FROM map_pois ORDER BY distance_km").fetchall()
        return [MapPOI(
            id=r["id"], name=r["name"], type=r["type"],
            description=r["description"], distance_km=r["distance_km"],
            direction=r["direction"], notes=r["notes"],
            discovered_at=r["discovered_at"],
            verified=bool(r["verified"])
        ) for r in rows]

    def get_pois_by_type(self, poi_type: str) -> list[MapPOI]:
        rows = self.conn.execute(
            "SELECT * FROM map_pois WHERE type=? ORDER BY distance_km", (poi_type,)
        ).fetchall()
        return [MapPOI(
            id=r["id"], name=r["name"], type=r["type"],
            description=r["description"], distance_km=r["distance_km"],
            direction=r["direction"], notes=r["notes"],
            discovered_at=r["discovered_at"],
            verified=bool(r["verified"])
        ) for r in rows]

    def delete_poi(self, poi_id: str):
        self.conn.execute("DELETE FROM map_pois WHERE id=?", (poi_id,))
        self.conn.commit()

    # --- Operating State ---

    def save_operating_state(self, state: OperatingState):
        self.conn.execute(
            "INSERT OR REPLACE INTO operating_state VALUES (?,?)",
            ("mode", state.mode)
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO operating_state VALUES (?,?)",
            ("power_remaining_hours", str(state.power_remaining_hours))
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO operating_state VALUES (?,?)",
            ("last_mode_change", state.last_mode_change or self._now())
        )
        self.conn.commit()

    def get_operating_state(self) -> OperatingState:
        rows = self.conn.execute(
            "SELECT key, value FROM operating_state"
        ).fetchall()
        data = {r["key"]: r["value"] for r in rows}
        return OperatingState(
            mode=data.get("mode", "standard"),
            power_remaining_hours=float(data.get("power_remaining_hours", 48.0)),
            last_mode_change=data.get("last_mode_change", "")
        )

    # --- Survivor State ---

    def save_survivor_state(self, key: str, value: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO survivor_state VALUES (?,?)", (key, value)
        )
        self.conn.commit()

    def get_survivor_state(self) -> dict:
        rows = self.conn.execute("SELECT key, value FROM survivor_state").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def save_hardware_profile(self, key: str, value: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO hardware_profile VALUES (?,?)", (key, value)
        )
        self.conn.commit()

    def get_hardware_profile(self) -> dict:
        rows = self.conn.execute("SELECT key, value FROM hardware_profile").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def is_initialized(self) -> bool:
        row = self.conn.execute(
            "SELECT value FROM operating_state WHERE key='initialized'"
        ).fetchone()
        return row is not None and row["value"] == "true"

    def mark_initialized(self):
        self.conn.execute(
            "INSERT OR REPLACE INTO operating_state VALUES (?,?)",
            ("initialized", "true")
        )
        self.conn.commit()

    def close(self):
        self.conn.close()
