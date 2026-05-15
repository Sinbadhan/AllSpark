import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from zipfile import ZipFile, ZIP_DEFLATED

from allspark.models import KnowledgeEntry, ExperienceLog, MapPOI

SKF_VERSION = "1.0"
SKF_MANIFEST = "manifest.json"
SKF_KNOWLEDGE = "knowledge.json"
SKF_EXPERIENCE = "experience.json"
SKF_LOCAL_DATA = "local_data.json"


def _generate_spark_id() -> str:
    return f"spark-{uuid.uuid4().hex[:4]}-{uuid.uuid4().hex[:4]}"


def _checksum(data: str) -> str:
    return f"sha256:{hashlib.sha256(data.encode('utf-8')).hexdigest()}"


class SKFPackage:
    def __init__(self):
        self.version = SKF_VERSION
        self.spark_id = ""
        self.created = ""
        self.knowledge_entries: list[KnowledgeEntry] = []
        self.experience_log: list[ExperienceLog] = []
        self.local_data: list[dict] = []
        self.metadata: dict = {}

    @classmethod
    def from_db(cls, db, spark_id: str = "",
                include_knowledge: bool = True,
                include_experience: bool = True,
                include_local: bool = True,
                category_filter: str = "",
                priority_max: int = 3,
                language: str = "") -> "SKFPackage":
        pkg = cls()
        pkg.spark_id = spark_id or _generate_spark_id()
        pkg.created = datetime.now().isoformat()

        if include_knowledge:
            if category_filter:
                rows = db.get_knowledge_by_category(category_filter)
            elif priority_max < 3:
                rows = db.get_knowledge_by_priority(priority_max)
            else:
                rows = db.conn.execute(
                    "SELECT * FROM knowledge ORDER BY priority, category"
                ).fetchall()
                rows = [db._row_to_entry(r) for r in rows]

            if language:
                rows = [k for k in rows if k.language == language]

            pkg.knowledge_entries = rows

        if include_experience:
            pkg.experience_log = db.get_recent_experiences(limit=1000)

        if include_local:
            poi_rows = db.conn.execute("SELECT * FROM map_pois").fetchall()
            for r in poi_rows:
                pkg.local_data.append({
                    "type": "map_poi",
                    "data": dict(r),
                })

        return pkg

    def to_dict(self) -> dict:
        knowledge_data = []
        for k in self.knowledge_entries:
            entry_dict = {
                "id": k.id,
                "category": k.category,
                "subcategory": k.subcategory,
                "priority": k.priority,
                "title": k.title,
                "content": {
                    "summary": k.summary,
                    "steps": k.steps,
                    "prerequisites": k.prerequisites,
                    "warnings": k.warnings,
                },
                "verification": k.verification,
                "source": k.source,
                "version": k.version,
                "language": k.language,
                "checksum": _checksum(k.summary),
            }
            knowledge_data.append(entry_dict)

        experience_data = []
        for e in self.experience_log:
            experience_data.append({
                "id": e.id,
                "timestamp": e.timestamp,
                "event": e.event,
                "outcome": e.outcome,
                "lesson": e.lesson,
            })

        manifest = {
            "skf": {
                "version": self.version,
                "spark_id": self.spark_id,
                "created": self.created,
                "stats": {
                    "knowledge_count": len(knowledge_data),
                    "experience_count": len(experience_data),
                    "local_data_count": len(self.local_data),
                },
            },
            "metadata": self.metadata,
        }

        return {
            SKF_MANIFEST: manifest,
            SKF_KNOWLEDGE: knowledge_data,
            SKF_EXPERIENCE: experience_data,
            SKF_LOCAL_DATA: self.local_data,
        }

    def export_to_file(self, path: str) -> str:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.to_dict()

        with ZipFile(str(path), 'w', ZIP_DEFLATED) as zf:
            zf.writestr(SKF_MANIFEST, json.dumps(data[SKF_MANIFEST], ensure_ascii=False, indent=2))
            zf.writestr(SKF_KNOWLEDGE, json.dumps(data[SKF_KNOWLEDGE], ensure_ascii=False, indent=2))
            zf.writestr(SKF_EXPERIENCE, json.dumps(data[SKF_EXPERIENCE], ensure_ascii=False, indent=2))
            if data[SKF_LOCAL_DATA]:
                zf.writestr(SKF_LOCAL_DATA, json.dumps(data[SKF_LOCAL_DATA], ensure_ascii=False, indent=2))

        return str(path)

    @classmethod
    def import_from_file(cls, path: str) -> "SKFPackage":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"SKF file not found: {path}")

        pkg = cls()

        with ZipFile(str(path), 'r') as zf:
            names = zf.namelist()

            manifest_raw = zf.read(SKF_MANIFEST).decode('utf-8')
            manifest = json.loads(manifest_raw)
            skf_meta = manifest.get("skf", {})
            pkg.version = skf_meta.get("version", SKF_VERSION)
            pkg.spark_id = skf_meta.get("spark_id", "")
            pkg.created = skf_meta.get("created", "")
            pkg.metadata = manifest.get("metadata", {})

            if SKF_KNOWLEDGE in names:
                knowledge_raw = zf.read(SKF_KNOWLEDGE).decode('utf-8')
                knowledge_data = json.loads(knowledge_raw)
                for item in knowledge_data:
                    content = item.get("content", {})
                    entry = KnowledgeEntry(
                        id=item["id"],
                        category=item.get("category", "uncategorized"),
                        subcategory=item.get("subcategory", ""),
                        priority=item.get("priority", 3),
                        title=item.get("title", ""),
                        summary=content.get("summary", ""),
                        steps=content.get("steps", []),
                        prerequisites=content.get("prerequisites", []),
                        warnings=content.get("warnings", []),
                        verification=item.get("verification", "unverified"),
                        source=item.get("source", "other_spark"),
                        version=item.get("version", 1),
                        language=item.get("language", "zh"),
                    )
                    pkg.knowledge_entries.append(entry)

            if SKF_EXPERIENCE in names:
                experience_raw = zf.read(SKF_EXPERIENCE).decode('utf-8')
                experience_data = json.loads(experience_raw)
                for item in experience_data:
                    entry = ExperienceLog(
                        id=item.get("id", str(uuid.uuid4())[:8]),
                        timestamp=item.get("timestamp", ""),
                        event=item.get("event", ""),
                        outcome=item.get("outcome", ""),
                        lesson=item.get("lesson", ""),
                    )
                    pkg.experience_log.append(entry)

            if SKF_LOCAL_DATA in names:
                local_raw = zf.read(SKF_LOCAL_DATA).decode('utf-8')
                pkg.local_data = json.loads(local_raw)

        return pkg

    def validate(self) -> list[str]:
        errors = []

        if not self.spark_id:
            errors.append("Missing spark_id in manifest")

        if not self.version:
            errors.append("Missing version in manifest")

        seen_ids = set()
        for k in self.knowledge_entries:
            if not k.id:
                errors.append("Knowledge entry missing id")
            elif k.id in seen_ids:
                errors.append(f"Duplicate knowledge id: {k.id}")
            seen_ids.add(k.id)

            if not k.title:
                errors.append(f"Knowledge {k.id}: missing title")
            if not k.summary:
                errors.append(f"Knowledge {k.id}: missing summary")
            if k.priority not in (0, 1, 2, 3):
                errors.append(f"Knowledge {k.id}: invalid priority {k.priority}")

        for e in self.experience_log:
            if not e.event:
                errors.append(f"Experience {e.id}: missing event")

        return errors

    def get_stats(self) -> dict:
        categories = {}
        for k in self.knowledge_entries:
            categories[k.category] = categories.get(k.category, 0) + 1

        return {
            "spark_id": self.spark_id,
            "created": self.created,
            "version": self.version,
            "knowledge_count": len(self.knowledge_entries),
            "experience_count": len(self.experience_log),
            "local_data_count": len(self.local_data),
            "categories": categories,
        }


def export_skf(db, path: str, spark_id: str = "",
               category: str = "", language: str = "",
               priority_max: int = 3) -> str:
    pkg = SKFPackage.from_db(
        db, spark_id=spark_id,
        category_filter=category,
        priority_max=priority_max,
        language=language,
    )
    return pkg.export_to_file(path)


def import_skf(db, path: str, verify: bool = True,
               skip_duplicates: bool = True) -> dict:
    pkg = SKFPackage.import_from_file(path)

    if verify:
        errors = pkg.validate()
        if errors:
            return {"status": "validation_error", "errors": errors}

    imported = {"knowledge": 0, "experience": 0, "local_data": 0, "skipped": 0}

    for k in pkg.knowledge_entries:
        if skip_duplicates:
            existing = db.get_knowledge(k.id)
            if existing:
                if existing.version >= k.version:
                    imported["skipped"] += 1
                    continue
        k.source = "other_spark"
        db.save_knowledge(k)
        imported["knowledge"] += 1

    for e in pkg.experience_log:
        db.save_experience(e)
        imported["experience"] += 1

    for item in pkg.local_data:
        if item.get("type") == "map_poi":
            data = item.get("data", {})
            poi = MapPOI(
                id=data.get("id", str(uuid.uuid4())[:8]),
                name=data.get("name", ""),
                type=data.get("type", "landmark"),
                description=data.get("description", ""),
                distance_km=data.get("distance_km", 0),
                direction=data.get("direction", ""),
                notes=data.get("notes", ""),
                discovered_at=data.get("discovered_at", ""),
                verified=data.get("verified", False),
            )
            db.save_poi(poi)
            imported["local_data"] += 1

    return {"status": "ok", "imported": imported, "source_spark": pkg.spark_id}
