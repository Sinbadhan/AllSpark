import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from allspark.core.models import (
    ExperienceLog,
    KnowledgeEntry,
    MapPOI,
    OperatingState,
    Resource,
    ResourceType,
    Task,
)
from allspark.core.tokenizer import tokenize, tokenize_query

logger = logging.getLogger(__name__)


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
            language=r["language"] if "language" in r.keys() else "zh",
            reviewer=r["reviewer"] if "reviewer" in r.keys() else "",
            qualification=r["qualification"] if "qualification" in r.keys() else "",
            review_date=r["review_date"] if "review_date" in r.keys() else "",
            citation=r["citation"] if "citation" in r.keys() else "",
            content_hash=r["content_hash"] if "content_hash" in r.keys() else "",
            signoff_version=r["signoff_version"] if "signoff_version" in r.keys() else 0,
        )

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            from allspark.core.config import DEFAULT_DB_PATH
            db_path = DEFAULT_DB_PATH
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
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
                last_updated TEXT NOT NULL,
                amount_known INTEGER NOT NULL DEFAULT 0,
                consumption_known INTEGER NOT NULL DEFAULT 0,
                intake_known INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'migration',
                people_count INTEGER NOT NULL DEFAULT 1,
                as_of TEXT NOT NULL DEFAULT '',
                capacity REAL NOT NULL DEFAULT 0,
                capacity_known INTEGER NOT NULL DEFAULT 0
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
                language TEXT DEFAULT 'zh',
                reviewer TEXT DEFAULT '',
                qualification TEXT DEFAULT '',
                review_date TEXT DEFAULT '',
                citation TEXT DEFAULT '',
                content_hash TEXT DEFAULT '',
                signoff_version INTEGER DEFAULT 0
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

            -- Phase 7: Goal System (PRD §10)
            CREATE TABLE IF NOT EXISTS goals (
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
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS milestones (
                id TEXT PRIMARY KEY,
                goal_id TEXT NOT NULL,
                description TEXT NOT NULL,
                done INTEGER DEFAULT 0,
                order_num INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                completed_at TEXT DEFAULT ''
            );

            -- Phase 7: Survival Timeline (PRD §4.4)
            CREATE TABLE IF NOT EXISTS timeline_events (
                id TEXT PRIMARY KEY,
                day INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                emotion TEXT DEFAULT 'neutral',
                related_goal_id TEXT DEFAULT '',
                auto_generated INTEGER DEFAULT 1
            );

            -- Phase 7: Spark Diary (PRD §4.7)
            CREATE TABLE IF NOT EXISTS diary_entries (
                id TEXT PRIMARY KEY,
                date TEXT NOT NULL,
                content TEXT NOT NULL,
                emotion TEXT DEFAULT 'neutral',
                keywords TEXT DEFAULT '[]',
                related_goal_id TEXT DEFAULT '',
                related_event TEXT DEFAULT '',
                is_public INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );

            -- Phase 7: Reset Log (PRD §4.2.5)
            CREATE TABLE IF NOT EXISTS reset_log (
                id TEXT PRIMARY KEY,
                level INTEGER NOT NULL,
                reason TEXT DEFAULT '',
                backup_id TEXT DEFAULT '',
                performed_by TEXT DEFAULT '',
                performed_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'accepted'
            );

            -- Phase 7: GPS location for spark itself
            CREATE TABLE IF NOT EXISTS spark_location (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            -- Phase 7: Psychological state tracking (PRD §4.6)
            CREATE TABLE IF NOT EXISTS psych_state (
                date TEXT PRIMARY KEY,
                loneliness REAL DEFAULT 0.0,
                stress REAL DEFAULT 0.0,
                interaction_count INTEGER DEFAULT 0,
                sleep_quality TEXT DEFAULT 'unknown',
                crisis_count INTEGER DEFAULT 0,
                notes TEXT DEFAULT ''
            );

            -- FTS for diary search
            CREATE VIRTUAL TABLE IF NOT EXISTS diary_fts USING fts5(
                date, content, keywords
            );

            -- PRD §4.3 / §5 Vector search cache
            CREATE TABLE IF NOT EXISTS knowledge_vectors (
                knowledge_id TEXT PRIMARY KEY,
                embedding TEXT NOT NULL,
                updated_at TEXT DEFAULT ''
            );

            -- PRD §3.1.3 Action Plans for warning protocol
            CREATE TABLE IF NOT EXISTS action_plans (
                id TEXT PRIMARY KEY,
                warning_id TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                solution_source TEXT NOT NULL,
                steps TEXT NOT NULL DEFAULT '[]',
                rank_score REAL DEFAULT 0.0,
                status TEXT DEFAULT 'proposed',
                created_at TEXT DEFAULT '',
                updated_at TEXT DEFAULT '',
                result TEXT DEFAULT '',
                title TEXT DEFAULT ''
            );
        """)
        self.conn.commit()
        self._migrate()

    def _migrate(self):
        cur = self.conn.cursor()
        # Pre-contract resource rows have no trustworthy provenance. Preserve
        # their raw values but migrate all field certainty to explicit unknown.
        for col, ctype in [
            ("amount_known", "INTEGER NOT NULL DEFAULT 0"),
            ("consumption_known", "INTEGER NOT NULL DEFAULT 0"),
            ("intake_known", "INTEGER NOT NULL DEFAULT 0"),
            ("source", "TEXT NOT NULL DEFAULT 'migration'"),
            ("people_count", "INTEGER NOT NULL DEFAULT 1"),
            ("as_of", "TEXT NOT NULL DEFAULT ''"),
            ("capacity", "REAL NOT NULL DEFAULT 0"),
            ("capacity_known", "INTEGER NOT NULL DEFAULT 0"),
        ]:
            try:
                cur.execute(f"SELECT {col} FROM resources LIMIT 1")
            except sqlite3.OperationalError:
                cur.execute(f"ALTER TABLE resources ADD COLUMN {col} {ctype}")
                self.conn.commit()
        try:
            cur.execute("SELECT language FROM knowledge LIMIT 1")
        except sqlite3.OperationalError:
            cur.execute("ALTER TABLE knowledge ADD COLUMN language TEXT DEFAULT 'zh'")
            self.conn.commit()

        # SHA-148: auditable expert-signoff columns on the knowledge table.
        for col, ctype in [
            ("reviewer", "TEXT DEFAULT ''"),
            ("qualification", "TEXT DEFAULT ''"),
            ("review_date", "TEXT DEFAULT ''"),
            ("citation", "TEXT DEFAULT ''"),
            ("content_hash", "TEXT DEFAULT ''"),
            ("signoff_version", "INTEGER DEFAULT 0"),
        ]:
            try:
                cur.execute(f"SELECT {col} FROM knowledge LIMIT 1")
            except sqlite3.OperationalError:
                cur.execute(f"ALTER TABLE knowledge ADD COLUMN {col} {ctype}")
                self.conn.commit()

        for col, ctype in [
            ("latitude", "REAL DEFAULT 0"),
            ("longitude", "REAL DEFAULT 0"),
            ("altitude", "REAL DEFAULT 0"),
        ]:
            try:
                cur.execute(f"SELECT {col} FROM map_pois LIMIT 1")
            except sqlite3.OperationalError:
                cur.execute(f"ALTER TABLE map_pois ADD COLUMN {col} {ctype}")
                self.conn.commit()

        try:
            cur.execute("SELECT status FROM reset_log LIMIT 1")
        except sqlite3.OperationalError:
            cur.execute(
                "ALTER TABLE reset_log "
                "ADD COLUMN status TEXT NOT NULL DEFAULT 'accepted'"
            )
            self.conn.commit()

    def _now(self) -> str:
        return datetime.now().isoformat()

    # --- Resources ---

    def upsert_resource(self, r: Resource):
        from allspark.core.models import RESOURCE_UNITS

        canonical_unit = RESOURCE_UNITS[r.type]
        if r.unit != canonical_unit:
            raise ValueError(
                f"resource {r.type.value} requires canonical unit {canonical_unit}"
            )
        self.conn.execute(
            """INSERT OR REPLACE INTO resources
               (type, current_amount, unit, daily_consumption, daily_intake,
                estimated_remaining_hours, last_updated, amount_known,
                consumption_known, intake_known, source, people_count, as_of,
                capacity, capacity_known)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r.type.value, r.current_amount, r.unit,
             r.daily_consumption, r.daily_intake,
             r.estimated_remaining_hours, self._now(),
             int(r.amount_known), int(r.consumption_known), int(r.intake_known),
             r.source, r.people_count, r.as_of, r.capacity, int(r.capacity_known))
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
            last_updated=row["last_updated"],
            amount_known=bool(row["amount_known"]),
            consumption_known=bool(row["consumption_known"]),
            intake_known=bool(row["intake_known"]),
            source=row["source"],
            people_count=row["people_count"],
            as_of=row["as_of"],
            capacity=row["capacity"],
            capacity_known=bool(row["capacity_known"]),
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
            last_updated=r["last_updated"],
            amount_known=bool(r["amount_known"]),
            consumption_known=bool(r["consumption_known"]),
            intake_known=bool(r["intake_known"]),
            source=r["source"],
            people_count=r["people_count"],
            as_of=r["as_of"],
            capacity=r["capacity"],
            capacity_known=bool(r["capacity_known"]),
        ) for r in rows]

    # --- Tasks ---

    def save_task(self, t: Task):
        self.conn.execute(
            "INSERT OR REPLACE INTO tasks VALUES (?,?,?,?,?,?,?,?)",
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
            """INSERT OR REPLACE INTO knowledge
               (id, category, subcategory, priority, title, summary, steps,
                prerequisites, warnings, verification, source, version,
                language, reviewer, qualification, review_date, citation,
                content_hash, signoff_version)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (k.id, k.category, k.subcategory, k.priority, k.title,
             k.summary, steps_json, prereq_json, warn_json,
             k.verification, k.source, k.version, k.language,
             k.reviewer, k.qualification, k.review_date, k.citation,
             k.content_hash, k.signoff_version)
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

    def search_knowledge(self, query: str, limit: int = 10, language: str = None) -> list[KnowledgeEntry]:
        results = []
        seen_ids = set()
        lang_clause = " AND k.language=?" if language else ""
        lang_params = [language] if language else []
        fts_rows = []
        try:
            fts_query = tokenize_query(query)
            if fts_query:
                # SHA-150: bm25 relevance (title/category weighted high) instead
                # of priority. The old LIKE %query% ordering never matched
                # Chinese substrings, so results fell back to priority order and
                # surfaced 伤口处理 before 煮沸净水法 for "如何安全净水". Fetch wider
                # than `limit` then re-rank so title-token matches surface above
                # long broad entries that merely mention the terms in their body.
                # knowledge_fts column order: (id, title, summary, steps,
                # category, subcategory); bm25 weights follow the same order.
                fetch_n = max(limit * 4, limit + 10)
                fts_rows = self.conn.execute(
                    f"""SELECT k.* FROM knowledge_fts
                        JOIN knowledge k ON k.id = knowledge_fts.id
                        WHERE knowledge_fts MATCH ?{lang_clause}
                        ORDER BY bm25(knowledge_fts, 0, 10.0, 3.0, 1.0, 4.0, 2.0)
                        LIMIT ?""",
                    [fts_query, *lang_params, fetch_n]
                ).fetchall()
        except Exception as e:
            logger.warning("FTS query failed, falling back to LIKE: %s", e)

        # Re-rank by title-term coverage. Counting matches, rather than using a
        # binary title hit, lets a specific title such as 电池取火法 outrank a
        # generic title that only shares 取火. Stable sort preserves bm25 order
        # when coverage is equal. Substring matching handles Chinese segmentation
        # differences and is case-insensitive for English.
        query_terms = [t.lower() for t in tokenize(query).split() if len(t) >= 2] if query else []
        if query_terms:
            fts_rows = sorted(
                fts_rows,
                key=lambda r: -sum(
                    qt in r["title"].lower() for qt in query_terms
                ),
            )
        for r in fts_rows:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                results.append(r)

        if len(results) < limit:
            keywords = query.split() or [query]
            for kw in keywords:
                if not kw:
                    continue
                like_lang_clause = " AND language=?" if language else ""
                like_params = [language] if language else []
                like_rows = self.conn.execute(
                    f"""SELECT * FROM knowledge
                       WHERE (title LIKE ? OR summary LIKE ? OR steps LIKE ?
                       OR category LIKE ? OR subcategory LIKE ?){like_lang_clause}
                       ORDER BY
                           CASE
                               WHEN title LIKE ? THEN 0
                               WHEN summary LIKE ? THEN 1
                               ELSE 2
                           END,
                           priority
                       LIMIT ?""",
                    [f"%{kw}%", f"%{kw}%", f"%{kw}%",
                     f"%{kw}%", f"%{kw}%", *like_params,
                     f"%{query}%", f"%{query}%", limit]
                ).fetchall()
                for r in like_rows:
                    if r["id"] not in seen_ids:
                        seen_ids.add(r["id"])
                        results.append(r)

        entries = []
        for r in results[:limit]:
            entries.append(self._row_to_entry(r))
        return entries

    def get_knowledge_by_category(self, category: str, subcategory: str = "",
                                    language: str = "") -> list[KnowledgeEntry]:
        if language:
            if subcategory:
                rows = self.conn.execute(
                    "SELECT * FROM knowledge WHERE category=? AND subcategory=? AND language=? ORDER BY priority",
                    (category, subcategory, language)
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM knowledge WHERE category=? AND language=? ORDER BY priority",
                    (category, language)
                ).fetchall()
        else:
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
            "INSERT OR REPLACE INTO map_pois VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (p.id, p.name, p.type, p.description, p.distance_km,
             p.direction, p.notes, p.discovered_at, 1 if p.verified else 0,
             getattr(p, 'latitude', 0.0),
             getattr(p, 'longitude', 0.0),
             getattr(p, 'altitude', 0.0))
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
        self.conn.execute(
            "INSERT OR REPLACE INTO operating_state VALUES (?,?)",
            ("mode_manual_override", "1" if state.mode_manual_override else "0")
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
            last_mode_change=data.get("last_mode_change", ""),
            mode_manual_override=data.get("mode_manual_override", "0") == "1",
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

    def finalize_initialization(self, language: str) -> None:
        """Atomically publish a prepared installation.

        Initialization draft rows are intentionally written by existing,
        self-committing methods.  These two operating-state keys are the sole
        publish marker and must become visible together.
        """
        if language not in ("zh", "en"):
            raise ValueError(f"Unsupported language: {language}")
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO operating_state VALUES (?,?)",
                ("language", language),
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO operating_state VALUES (?,?)",
                ("initialized", "true"),
            )

    def mark_uninitialized(self):
        self.conn.execute(
            "DELETE FROM operating_state WHERE key='initialized'"
        )
        self.conn.commit()

    def close(self):
        self.conn.close()

    # --- Community Members ---

    def get_community_members(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM community_members").fetchall()
        return [dict(r) for r in rows]

    def upsert_community_member(self, member_id: str, name: str, role: str,
                                domains: str, skills: str, health_status: str,
                                psychological_stability: float, contribution_score: float,
                                joined_at: str, last_active: str, is_commander: int):
        self.conn.execute(
            "INSERT OR REPLACE INTO community_members VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (member_id, name, role, domains, skills, health_status,
             psychological_stability, contribution_score, joined_at,
             last_active, is_commander)
        )
        self.conn.commit()

    def delete_community_member(self, member_id: str):
        self.conn.execute("DELETE FROM community_members WHERE id=?", (member_id,))
        self.conn.commit()

    # --- Conflicts ---

    def get_conflicts(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM conflicts").fetchall()
        return [dict(r) for r in rows]

    def upsert_conflict(self, conflict_id: str, title: str, description: str,
                        parties: str, status: str, mediator: str, resolution: str,
                        created_at: str, resolved_at: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO conflicts VALUES (?,?,?,?,?,?,?,?,?)",
            (conflict_id, title, description, parties, status,
             mediator, resolution, created_at, resolved_at)
        )
        self.conn.commit()

    # --- Trade Offers ---

    def get_trade_offers(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM trade_offers").fetchall()
        return [dict(r) for r in rows]

    def upsert_trade_offer(self, offer_id: str, proposer_id: str,
                           target_spark_id: str, offer_knowledge_ids: str,
                           request_knowledge_ids: str, status: str,
                           created_at: str, completed_at: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO trade_offers VALUES (?,?,?,?,?,?,?,?)",
            (offer_id, proposer_id, target_spark_id,
             offer_knowledge_ids, request_knowledge_ids,
             status, created_at, completed_at)
        )
        self.conn.commit()

    # --- Knowledge Aggregation ---

    def get_knowledge_categories(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT category, COUNT(*) as cnt FROM knowledge GROUP BY category"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_knowledge_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM knowledge").fetchone()
        return row["cnt"]

    def get_knowledge_ids(self) -> list[str]:
        rows = self.conn.execute("SELECT id FROM knowledge").fetchall()
        return [r["id"] for r in rows]

    def get_distinct_knowledge_categories(self) -> list[str]:
        rows = self.conn.execute("SELECT DISTINCT category FROM knowledge").fetchall()
        return [r["category"] for r in rows]

    # --- Integrity Check ---

    def check_integrity(self) -> bool:
        result = self.conn.execute("PRAGMA integrity_check").fetchone()
        return result[0] == "ok"

    # --- Goals ---

    def save_goal(self, goal):
        self.conn.execute(
            "INSERT OR REPLACE INTO goals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (goal.id, goal.title, goal.description, goal.goal_type,
             goal.category, goal.priority, goal.status, goal.source,
             goal.progress, goal.deadline, goal.triggers, goal.rationale,
             goal.created_by, goal.milestone_count, goal.milestone_done,
             goal.created_at, self._now())
        )
        self.conn.commit()

    def get_goal(self, goal_id: str):
        row = self.conn.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone()
        if not row:
            return None
        from allspark.core.models import Goal
        d = dict(row)
        return Goal(
            id=d["id"], title=d["title"], description=d["description"],
            goal_type=d["goal_type"], category=d["category"],
            priority=d["priority"], status=d["status"], source=d["source"],
            progress=d["progress"], deadline=d["deadline"],
            triggers=d["triggers"], rationale=d["rationale"],
            created_by=d["created_by"],
            milestone_count=d["milestone_count"], milestone_done=d["milestone_done"],
            created_at=d["created_at"], updated_at=d["updated_at"],
        )

    def get_active_goals(self):
        from allspark.core.models import Goal
        rows = self.conn.execute(
            "SELECT * FROM goals WHERE status='active' ORDER BY priority, created_at"
        ).fetchall()
        results = []
        for d in rows:
            d = dict(d)
            results.append(Goal(
                id=d["id"], title=d["title"], description=d["description"],
                goal_type=d["goal_type"], category=d["category"],
                priority=d["priority"], status=d["status"], source=d["source"],
                progress=d["progress"], deadline=d["deadline"],
                triggers=d["triggers"], rationale=d["rationale"],
                created_by=d["created_by"],
                milestone_count=d["milestone_count"], milestone_done=d["milestone_done"],
                created_at=d["created_at"], updated_at=d["updated_at"],
            ))
        return results

    def get_goals_by_category(self, category: str):
        from allspark.core.models import Goal
        rows = self.conn.execute(
            "SELECT * FROM goals WHERE category=? ORDER BY priority", (category,)
        ).fetchall()
        results = []
        for d in rows:
            d = dict(d)
            results.append(Goal(
                id=d["id"], title=d["title"], description=d["description"],
                goal_type=d["goal_type"], category=d["category"],
                priority=d["priority"], status=d["status"], source=d["source"],
                progress=d["progress"], deadline=d["deadline"],
                triggers=d["triggers"], rationale=d["rationale"],
                created_by=d["created_by"],
                milestone_count=d["milestone_count"], milestone_done=d["milestone_done"],
                created_at=d["created_at"], updated_at=d["updated_at"],
            ))
        return results

    def update_goal_status(self, goal_id: str, status: str):
        self.conn.execute(
            "UPDATE goals SET status=?, updated_at=? WHERE id=?",
            (status, self._now(), goal_id)
        )
        self.conn.commit()

    def update_goal_progress(self, goal_id: str, progress: float,
                             milestone_done: int = None):
        if milestone_done is not None:
            self.conn.execute(
                "UPDATE goals SET progress=?, milestone_done=?, updated_at=? WHERE id=?",
                (progress, milestone_done, self._now(), goal_id)
            )
        else:
            self.conn.execute(
                "UPDATE goals SET progress=?, updated_at=? WHERE id=?",
                (progress, self._now(), goal_id)
            )
        self.conn.commit()

    # --- Milestones ---

    def save_milestone(self, milestone):
        self.conn.execute(
            "INSERT OR REPLACE INTO milestones VALUES (?,?,?,?,?,?,?)",
            (milestone.id, milestone.goal_id, milestone.description,
             1 if milestone.done else 0, milestone.order,
             milestone.created_at, milestone.completed_at)
        )
        self.conn.commit()

    def get_milestones_by_goal(self, goal_id: str):
        from allspark.core.models import Milestone
        rows = self.conn.execute(
            "SELECT * FROM milestones WHERE goal_id=? ORDER BY order_num",
            (goal_id,)
        ).fetchall()
        results = []
        for d in rows:
            d = dict(d)
            results.append(Milestone(
                id=d["id"], goal_id=d["goal_id"],
                description=d["description"],
                done=bool(d["done"]), order=d["order_num"],
                created_at=d["created_at"], completed_at=d["completed_at"],
            ))
        return results

    def complete_milestone(self, milestone_id: str):
        self.conn.execute(
            "UPDATE milestones SET done=1, completed_at=? WHERE id=?",
            (self._now(), milestone_id)
        )
        self.conn.commit()

    # --- Diary ---

    def save_diary_entry(self, entry):
        self.conn.execute(
            "INSERT OR REPLACE INTO diary_entries VALUES (?,?,?,?,?,?,?,?,?)",
            (entry.id, entry.date, entry.content, entry.emotion,
             entry.keywords, entry.related_goal_id, entry.related_event,
             1 if entry.is_public else 0, entry.created_at)
        )
        self.conn.commit()

    def get_diary_entry(self, entry_id: str):
        from allspark.core.models import DiaryEntry
        row = self.conn.execute(
            "SELECT * FROM diary_entries WHERE id=?", (entry_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        return DiaryEntry(
            id=d["id"], date=d["date"], content=d["content"],
            emotion=d["emotion"], keywords=d["keywords"],
            related_goal_id=d["related_goal_id"],
            related_event=d["related_event"],
            is_public=bool(d["is_public"]), created_at=d["created_at"],
        )

    def get_diary_entries_by_date(self, date: str):
        from allspark.core.models import DiaryEntry
        rows = self.conn.execute(
            "SELECT * FROM diary_entries WHERE date=? ORDER BY created_at", (date,)
        ).fetchall()
        results = []
        for d in rows:
            d = dict(d)
            results.append(DiaryEntry(
                id=d["id"], date=d["date"], content=d["content"],
                emotion=d["emotion"], keywords=d["keywords"],
                related_goal_id=d["related_goal_id"],
                related_event=d["related_event"],
                is_public=bool(d["is_public"]), created_at=d["created_at"],
            ))
        return results

    def get_diary_entries_by_range(self, start_date: str, end_date: str):
        from allspark.core.models import DiaryEntry
        rows = self.conn.execute(
            "SELECT * FROM diary_entries WHERE date BETWEEN ? AND ? ORDER BY date",
            (start_date, end_date)
        ).fetchall()
        results = []
        for d in rows:
            d = dict(d)
            results.append(DiaryEntry(
                id=d["id"], date=d["date"], content=d["content"],
                emotion=d["emotion"], keywords=d["keywords"],
                related_goal_id=d["related_goal_id"],
                related_event=d["related_event"],
                is_public=bool(d["is_public"]), created_at=d["created_at"],
            ))
        return results

    def search_diary(self, query: str):
        from allspark.core.models import DiaryEntry
        rows = self.conn.execute(
            "SELECT * FROM diary_entries WHERE content LIKE ? ORDER BY date DESC",
            (f'%{query}%',)
        ).fetchall()
        results = []
        for d in rows:
            d = dict(d)
            results.append(DiaryEntry(
                id=d["id"], date=d["date"], content=d["content"],
                emotion=d["emotion"], keywords=d["keywords"],
                related_goal_id=d["related_goal_id"],
                related_event=d["related_event"],
                is_public=bool(d["is_public"]), created_at=d["created_at"],
            ))
        return results

    def delete_diary_entry(self, entry_id: str):
        self.conn.execute("DELETE FROM diary_entries WHERE id=?", (entry_id,))
        self.conn.commit()

    # --- Timeline ---

    def save_timeline_event(self, event):
        self.conn.execute(
            "INSERT OR REPLACE INTO timeline_events VALUES (?,?,?,?,?,?,?,?,?)",
            (event.id, event.day, event.timestamp, event.event_type,
             event.title, event.description, event.emotion,
             event.related_goal_id, 1 if event.auto_generated else 0)
        )
        self.conn.commit()

    def get_timeline_events(self, day: int = None, limit: int = 50):
        from allspark.core.models import TimelineEvent
        if day is not None:
            rows = self.conn.execute(
                "SELECT * FROM timeline_events WHERE day=? ORDER BY timestamp",
                (day,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM timeline_events ORDER BY day DESC, timestamp DESC LIMIT ?",
                (limit,)
            ).fetchall()
        results = []
        for d in rows:
            d = dict(d)
            results.append(TimelineEvent(
                id=d["id"], day=d["day"], timestamp=d["timestamp"],
                event_type=d["event_type"], title=d["title"],
                description=d["description"], emotion=d["emotion"],
                related_goal_id=d["related_goal_id"],
                auto_generated=bool(d["auto_generated"]),
            ))
        return results

    def get_timeline_events_by_type(self, event_type: str, limit: int = 20):
        from allspark.core.models import TimelineEvent
        rows = self.conn.execute(
            "SELECT * FROM timeline_events WHERE event_type=? ORDER BY day DESC, timestamp DESC LIMIT ?",
            (event_type, limit)
        ).fetchall()
        results = []
        for d in rows:
            d = dict(d)
            results.append(TimelineEvent(
                id=d["id"], day=d["day"], timestamp=d["timestamp"],
                event_type=d["event_type"], title=d["title"],
                description=d["description"], emotion=d["emotion"],
                related_goal_id=d["related_goal_id"],
                auto_generated=bool(d["auto_generated"]),
            ))
        return results

    def get_max_day(self) -> int:
        row = self.conn.execute("SELECT MAX(day) as max_day FROM timeline_events").fetchone()
        return row["max_day"] if row and row["max_day"] else 0

    # --- Reset Log ---

    def save_reset_log(self, reset_id: str, level: int, reason: str = "",
                       backup_id: str = "", performed_by: str = "",
                       status: str = "accepted", performed_at: str | None = None):
        self.conn.execute(
            "INSERT INTO reset_log "
            "(id, level, reason, backup_id, performed_by, performed_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                reset_id,
                level,
                reason,
                backup_id,
                performed_by,
                performed_at or self._now(),
                status,
            ),
        )
        self.conn.commit()

    def get_reset_logs(self, limit: int = 10):
        rows = self.conn.execute(
            "SELECT * FROM reset_log ORDER BY performed_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_latest_accepted_reset(self) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM reset_log WHERE status='accepted' "
            "ORDER BY performed_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def get_application_tables(self) -> list[str]:
        """Return top-level application tables, excluding SQLite/FTS internals."""
        rows = self.conn.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        virtual_tables = {
            row["name"]
            for row in rows
            if (row["sql"] or "").lstrip().upper().startswith("CREATE VIRTUAL TABLE")
        }
        return sorted(
            row["name"]
            for row in rows
            if not any(
                row["name"].startswith(f"{virtual_table}_")
                for virtual_table in virtual_tables
            )
        )

    # --- Spark Location (GPS) ---

    def save_location(self, key: str, value: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO spark_location VALUES (?,?)",
            (key, value)
        )
        self.conn.commit()

    def get_location(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM spark_location WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def get_all_location(self) -> dict:
        rows = self.conn.execute("SELECT * FROM spark_location").fetchall()
        return {r["key"]: r["value"] for r in rows}

    # --- Psychological State ---

    def save_psych_state(self, date: str, loneliness: float, stress: float,
                         interaction_count: int, sleep_quality: str = "unknown",
                         crisis_count: int = 0, notes: str = ""):
        self.conn.execute(
            "INSERT OR REPLACE INTO psych_state VALUES (?,?,?,?,?,?,?)",
            (date, loneliness, stress, interaction_count,
             sleep_quality, crisis_count, notes)
        )
        self.conn.commit()

    def get_psych_state(self, date: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM psych_state WHERE date=?", (date,)
        ).fetchone()
        return dict(row) if row else None

    def get_psych_state_range(self, start_date: str, end_date: str) -> list:
        rows = self.conn.execute(
            "SELECT * FROM psych_state WHERE date BETWEEN ? AND ? ORDER BY date",
            (start_date, end_date)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_latest_psych_state(self) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM psych_state ORDER BY date DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    # ─── Knowledge Vectors (PRD §4.3 / §5) ──────────────────────────────

    def save_knowledge_vector(self, knowledge_id: str, embedding: list[float]):
        import json
        from datetime import datetime
        self.conn.execute(
            """
            INSERT OR REPLACE INTO knowledge_vectors (knowledge_id, embedding, updated_at)
            VALUES (?, ?, ?)
            """,
            (knowledge_id, json.dumps(embedding), datetime.now().isoformat()),
        )
        self.conn.commit()

    def get_knowledge_vectors(self):
        return self.conn.execute(
            "SELECT knowledge_id, embedding, updated_at FROM knowledge_vectors"
        ).fetchall()

    # ─── Action Plans (PRD §3.1.3) ──────────────────────────────────────

    def save_action_plan(self, plan):
        import json
        self.conn.execute("""
            INSERT OR REPLACE INTO action_plans
            (id, warning_id, resource_type, solution_source, steps, rank_score,
             status, created_at, updated_at, result, title)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            plan.id, plan.warning_id, plan.resource_type, plan.solution_source,
            json.dumps(plan.steps, ensure_ascii=False), plan.rank_score,
            plan.status, plan.created_at, plan.updated_at, plan.result, plan.title,
        ))
        self.conn.commit()

    def get_action_plan(self, plan_id: str):
        import json

        from allspark.core.models import ActionPlan
        row = self.conn.execute(
            "SELECT * FROM action_plans WHERE id=?", (plan_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        return ActionPlan(
            id=d["id"], warning_id=d["warning_id"], resource_type=d["resource_type"],
            solution_source=d["solution_source"],
            steps=json.loads(d["steps"]) if d["steps"] else [],
            rank_score=d["rank_score"], status=d["status"],
            created_at=d["created_at"], updated_at=d["updated_at"],
            result=d["result"], title=d["title"],
        )

    def get_action_plans_by_warning(self, warning_id: str, status: str = None):
        import json

        from allspark.core.models import ActionPlan
        if status:
            rows = self.conn.execute(
                "SELECT * FROM action_plans WHERE warning_id=? AND status=? ORDER BY rank_score DESC",
                (warning_id, status),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM action_plans WHERE warning_id=? ORDER BY rank_score DESC",
                (warning_id,),
            ).fetchall()
        results = []
        for d in rows:
            d = dict(d)
            results.append(ActionPlan(
                id=d["id"], warning_id=d["warning_id"], resource_type=d["resource_type"],
                solution_source=d["solution_source"],
                steps=json.loads(d["steps"]) if d["steps"] else [],
                rank_score=d["rank_score"], status=d["status"],
                created_at=d["created_at"], updated_at=d["updated_at"],
                result=d["result"], title=d["title"],
            ))
        return results
