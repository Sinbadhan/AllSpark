import hashlib
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from allspark.core.i18n import t
from allspark.core.models import (
    ExperienceLog,
    KnowledgeEntry,
    KnowledgeValidationError,
    MapPOI,
    externalize_knowledge_evidence,
    normalize_knowledge_evidence,
    review_claim_payload,
    validate_knowledge_entry_schema,
)

logger = logging.getLogger(__name__)

SKF_VERSION = "1.0"
SKF_MANIFEST = "manifest.json"
SKF_KNOWLEDGE = "knowledge.json"
SKF_EXPERIENCE = "experience.json"
SKF_LOCAL_DATA = "local_data.json"

_SKF_ALLOWED_MEMBERS = {SKF_MANIFEST, SKF_KNOWLEDGE, SKF_EXPERIENCE, SKF_LOCAL_DATA}
_SKF_MEMBER_LIMITS = {
    SKF_MANIFEST: 1_048_576,
    SKF_KNOWLEDGE: 8_388_608,
    SKF_EXPERIENCE: 4_194_304,
    SKF_LOCAL_DATA: 4_194_304,
}
_SKF_TOTAL_UNCOMPRESSED_MAX = 16_777_216
_SKF_ARCHIVE_COMPRESSED_MAX = 16_777_216
_SKF_COMPRESSION_RATIO_MAX = 200
_SKF_KNOWLEDGE_ENTRIES_MAX = 2048
_SKF_EXPERIENCE_ENTRIES_MAX = 5000
_SKF_LOCAL_ENTRIES_MAX = 5000
_SKF_CONTENT_LIST_MAX = 128
_SKF_CONTENT_TEXT_MAX = 4096


class SKFArchiveValidationError(ValueError):
    pass


def _preflight_archive(zf: ZipFile) -> dict[str, ZipInfo]:
    infos = zf.infolist()
    names = [info.filename for info in infos]
    unknown = set(names) - _SKF_ALLOWED_MEMBERS
    if unknown:
        raise SKFArchiveValidationError(f"Unexpected SKF members: {sorted(unknown)}")
    duplicates = {name for name in names if names.count(name) > 1}
    if duplicates:
        raise SKFArchiveValidationError(f"Duplicate SKF members: {sorted(duplicates)}")
    by_name = {info.filename: info for info in infos}
    if SKF_MANIFEST not in by_name:
        raise SKFArchiveValidationError("Missing manifest.json")
    total = 0
    for name, info in by_name.items():
        limit = _SKF_MEMBER_LIMITS[name]
        if info.file_size > limit:
            raise SKFArchiveValidationError(f"SKF member too large: {name}")
        if info.file_size and info.compress_size == 0:
            raise SKFArchiveValidationError(f"Invalid compressed size: {name}")
        if info.compress_size and info.file_size / info.compress_size > _SKF_COMPRESSION_RATIO_MAX:
            raise SKFArchiveValidationError(f"SKF compression ratio too high: {name}")
        total += info.file_size
    if total > _SKF_TOTAL_UNCOMPRESSED_MAX:
        raise SKFArchiveValidationError("SKF total uncompressed size too large")
    return by_name


def _read_member(zf: ZipFile, info: ZipInfo, name: str):
    limit = _SKF_MEMBER_LIMITS[name]
    with zf.open(info) as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise SKFArchiveValidationError(f"SKF member exceeded read limit: {name}")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SKFArchiveValidationError(f"Invalid JSON in {name}") from exc


def _validate_content_strings(values, field: str) -> None:
    if not isinstance(values, list) or len(values) > _SKF_CONTENT_LIST_MAX:
        raise SKFArchiveValidationError(f"Invalid {field} count")
    if any(not isinstance(value, str) or len(value) > _SKF_CONTENT_TEXT_MAX for value in values):
        raise SKFArchiveValidationError(f"Invalid {field} item")


def _validate_knowledge_item(item: object) -> None:
    if not isinstance(item, dict):
        raise SKFArchiveValidationError("Knowledge entry must be an object")
    content = item.get("content", {})
    if not isinstance(content, dict):
        raise SKFArchiveValidationError("Knowledge content must be an object")
    raw_id = item.get("id")
    if not isinstance(raw_id, str) or not raw_id.strip():
        raise SKFArchiveValidationError("Knowledge id must be stable non-empty text")
    if not _sanitize_kf_field(raw_id, "id", ""):
        raise SKFArchiveValidationError("Knowledge id is empty after sanitization")
    limits = {"title": 1024, "summary": 16384}
    for field, limit in limits.items():
        value = item.get(field) if field == "title" else content.get(field, "")
        if not isinstance(value, str) or len(value) > limit:
            raise SKFArchiveValidationError(f"Invalid knowledge {field}")
    scalar_limits = {
        "id": 128, "category": 64, "subcategory": 64, "verification": 32,
        "source": 64, "verification_claim": 32, "source_claim": 64,
        "language": 8,
    }
    for field, limit in scalar_limits.items():
        value = item.get(field, "")
        if not isinstance(value, str) or len(value) > limit:
            raise SKFArchiveValidationError(f"Invalid knowledge {field}")
    priority = item.get("priority", 3)
    version = item.get("version", 1)
    if not isinstance(priority, int) or isinstance(priority, bool) or priority not in (0, 1, 2, 3):
        raise SKFArchiveValidationError("Invalid knowledge priority")
    if not isinstance(version, int) or isinstance(version, bool) or not 0 <= version <= 1_000_000:
        raise SKFArchiveValidationError("Invalid knowledge version")
    for field in ("steps", "prerequisites", "warnings"):
        _validate_content_strings(content.get(field, []), field)


def _generate_spark_id() -> str:
    return f"spark-{uuid.uuid4().hex[:4]}-{uuid.uuid4().hex[:4]}"


# SHA-147: SKF packages are untrusted input. These metadata fields are rendered
# into Web pages (Repository/Dashboard) and must never carry HTML/JS
# metacharacters. Strip them at import time as defense-in-depth alongside
# output-side escaping (escHtml) in the templates.
_HTML_META_RE = re.compile(r'[<>"\'`&]')
_FIELD_MAXLEN = {
    "id": 128,
    "category": 64,
    "subcategory": 64,
    "verification": 32,
    "source": 64,
}


def _sanitize_kf_field(value, field: str, default: str = "") -> str:
    """Coerce, strip HTML metacharacters, and truncate an untrusted SKF field.

    Returns ``default`` when the value is missing/empty after sanitization.
    """
    if value is None:
        return default
    if not isinstance(value, str):
        value = str(value)
    value = _HTML_META_RE.sub("", value).strip()
    # Categories and subcategories are interpolated as one URL path segment by
    # the Web API. A closing-tag slash would otherwise turn one segment into
    # several after URL decoding and make the imported entry unreachable.
    if field in {"category", "subcategory"}:
        value = value.replace("/", "")
    max_len = _FIELD_MAXLEN.get(field, 128)
    if len(value) > max_len:
        value = value[:max_len]
    return value or default


def _checksum(data: str) -> str:
    return f"sha256:{hashlib.sha256(data.encode('utf-8')).hexdigest()}"


def _entry_checksum(k: KnowledgeEntry) -> str:
    payload = {
        "id": k.id,
        "category": k.category,
        "subcategory": k.subcategory,
        "priority": k.priority,
        "title": k.title,
        "summary": k.summary,
        "steps": k.steps,
        "prerequisites": k.prerequisites,
        "warnings": k.warnings,
        "verification": k.verification,
        "source": k.source,
        "version": k.version,
        "language": k.language,
    }
    evidence_fields = {
        "references": k.references,
        "field_records": k.field_records,
        "applicable_when": k.applicable_when,
        "contraindications": k.contraindications,
        "review_claim": review_claim_payload(k),
    }
    if any(evidence_fields.values()):
        payload.update(evidence_fields)
    if k.verification_claim or k.source_claim:
        payload["verification_claim"] = k.verification_claim
        payload["source_claim"] = k.source_claim
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return _checksum(canonical)


class SKFPackage:
    def __init__(self):
        self.version = SKF_VERSION
        self.spark_id = ""
        self.created = ""
        self.knowledge_entries: list[KnowledgeEntry] = []
        self.experience_log: list[ExperienceLog] = []
        self.local_data: list[dict] = []
        self.metadata: dict = {}
        self._checksum_errors: list[str] = []
        self._import_errors: list[str] = []

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
                rows = db.get_knowledge_by_priority(max_priority=priority_max)
            else:
                rows = db.get_knowledge_by_priority(max_priority=3)

            if language:
                rows = [k for k in rows if k.language == language]

            pkg.knowledge_entries = rows

        if include_experience:
            pkg.experience_log = db.get_recent_experiences(limit=1000)

        if include_local:
            for poi in db.get_all_pois():
                pkg.local_data.append({
                    "type": "map_poi",
                    "data": {
                        "id": poi.id,
                        "name": poi.name,
                        "type": poi.type,
                        "description": poi.description,
                        "distance_km": poi.distance_km,
                        "direction": poi.direction,
                        "notes": poi.notes,
                        "discovered_at": poi.discovered_at,
                        "verified": 1 if poi.verified else 0,
                    },
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
                    "applicable_when": k.applicable_when,
                    "contraindications": k.contraindications,
                },
                "references": k.references,
                "field_records": k.field_records,
                "verification": k.verification,
                "source": k.source,
                "verification_claim": k.verification_claim,
                "source_claim": k.source_claim,
                "review_claim": review_claim_payload(k),
                "version": k.version,
                "language": k.language,
                "checksum": _entry_checksum(k),
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
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = self.to_dict()

        with ZipFile(str(dest), 'w', ZIP_DEFLATED) as zf:
            zf.writestr(SKF_MANIFEST, json.dumps(data[SKF_MANIFEST], ensure_ascii=False, indent=2))
            zf.writestr(SKF_KNOWLEDGE, json.dumps(data[SKF_KNOWLEDGE], ensure_ascii=False, indent=2))
            zf.writestr(SKF_EXPERIENCE, json.dumps(data[SKF_EXPERIENCE], ensure_ascii=False, indent=2))
            if data[SKF_LOCAL_DATA]:
                zf.writestr(SKF_LOCAL_DATA, json.dumps(data[SKF_LOCAL_DATA], ensure_ascii=False, indent=2))

        return str(dest)

    @classmethod
    def import_from_file(cls, path: str) -> "SKFPackage":
        src = Path(path)
        if not src.exists():
            raise FileNotFoundError(f"SKF file not found: {src}")
        if src.stat().st_size > _SKF_ARCHIVE_COMPRESSED_MAX:
            raise SKFArchiveValidationError("SKF archive compressed size too large")

        pkg = cls()

        with ZipFile(str(src), 'r') as zf:
            members = _preflight_archive(zf)
            names = set(members)

            manifest = _read_member(zf, members[SKF_MANIFEST], SKF_MANIFEST)
            if not isinstance(manifest, dict):
                raise SKFArchiveValidationError("Manifest must be an object")
            skf_meta = manifest.get("skf", {})
            pkg.version = skf_meta.get("version", SKF_VERSION)
            pkg.spark_id = skf_meta.get("spark_id", "")
            pkg.created = skf_meta.get("created", "")
            pkg.metadata = manifest.get("metadata", {})

            if SKF_KNOWLEDGE in names:
                knowledge_data = _read_member(zf, members[SKF_KNOWLEDGE], SKF_KNOWLEDGE)
                if not isinstance(knowledge_data, list) or len(knowledge_data) > _SKF_KNOWLEDGE_ENTRIES_MAX:
                    raise SKFArchiveValidationError("Invalid knowledge entry count")
                for item in knowledge_data:
                    _validate_knowledge_item(item)
                    content = item.get("content", {})
                    entry = KnowledgeEntry(
                        id=_sanitize_kf_field(item.get("id"), "id", ""),
                        category=_sanitize_kf_field(item.get("category"), "category", "uncategorized"),
                        subcategory=_sanitize_kf_field(item.get("subcategory"), "subcategory", ""),
                        priority=item.get("priority", 3),
                        title=item.get("title", ""),
                        summary=content.get("summary", ""),
                        steps=content.get("steps", []),
                        prerequisites=content.get("prerequisites", []),
                        warnings=content.get("warnings", []),
                        applicable_when=content.get("applicable_when", []),
                        contraindications=content.get("contraindications", []),
                        references=item.get("references", []),
                        field_records=item.get("field_records", []),
                        verification=_sanitize_kf_field(item.get("verification"), "verification", "unverified"),
                        source=_sanitize_kf_field(item.get("source"), "source", "other_spark"),
                        verification_claim=_sanitize_kf_field(
                            item.get("verification_claim"), "verification", ""
                        ),
                        source_claim=_sanitize_kf_field(item.get("source_claim"), "source", ""),
                        review_claim=item.get("review_claim", {}),
                        version=item.get("version", 1),
                        language=item.get("language", "zh"),
                    )
                    try:
                        validate_knowledge_entry_schema(entry)
                        normalize_knowledge_evidence(entry)
                    except KnowledgeValidationError as exc:
                        pkg._import_errors.append(
                            f"Knowledge {entry.id}: invalid evidence envelope ({exc.reason})"
                        )
                        continue
                    pkg.knowledge_entries.append(entry)

            pkg._checksum_errors = []
            if SKF_KNOWLEDGE in names:
                for item in knowledge_data:
                    stored_checksum = item.get("checksum", "")
                    if stored_checksum:
                        content = item.get("content", {})
                        check_entry = KnowledgeEntry(
                            id=item["id"],
                            category=item.get("category", "uncategorized"),
                            subcategory=item.get("subcategory", ""),
                            priority=item.get("priority", 3),
                            title=item.get("title", ""),
                            summary=content.get("summary", ""),
                            steps=content.get("steps", []),
                            prerequisites=content.get("prerequisites", []),
                            warnings=content.get("warnings", []),
                            applicable_when=content.get("applicable_when", []),
                            contraindications=content.get("contraindications", []),
                            references=item.get("references", []),
                            field_records=item.get("field_records", []),
                            verification=item.get("verification", "unverified"),
                            source=item.get("source", "other_spark"),
                            verification_claim=item.get("verification_claim", ""),
                            source_claim=item.get("source_claim", ""),
                            review_claim=item.get("review_claim", {}),
                            version=item.get("version", 1),
                            language=item.get("language", "zh"),
                        )
                        computed = _entry_checksum(check_entry)
                        if stored_checksum != computed:
                            pkg._checksum_errors.append(
                                f"Knowledge {item['id']}: checksum mismatch "
                                f"(stored={stored_checksum}, computed={computed})"
                            )

            if SKF_EXPERIENCE in names:
                experience_data = _read_member(zf, members[SKF_EXPERIENCE], SKF_EXPERIENCE)
                if not isinstance(experience_data, list) or len(experience_data) > _SKF_EXPERIENCE_ENTRIES_MAX:
                    raise SKFArchiveValidationError("Invalid experience entry count")
                for item in experience_data:
                    if not isinstance(item, dict):
                        raise SKFArchiveValidationError("Experience entry must be an object")
                    exp_entry = ExperienceLog(
                        id=item.get("id", str(uuid.uuid4())[:8]),
                        timestamp=item.get("timestamp", ""),
                        event=item.get("event", ""),
                        outcome=item.get("outcome", ""),
                        lesson=item.get("lesson", ""),
                    )
                    pkg.experience_log.append(exp_entry)

            if SKF_LOCAL_DATA in names:
                local_data = _read_member(zf, members[SKF_LOCAL_DATA], SKF_LOCAL_DATA)
                if not isinstance(local_data, list) or len(local_data) > _SKF_LOCAL_ENTRIES_MAX:
                    raise SKFArchiveValidationError("Invalid local data entry count")
                pkg.local_data = local_data

        return pkg

    def validate(self, *, check_checksums: bool = True) -> list[str]:
        errors = []

        if not self.spark_id:
            errors.append("Missing spark_id in manifest")

        if not self.version:
            errors.append("Missing version in manifest")

        if check_checksums:
            errors.extend(getattr(self, '_checksum_errors', []))
        errors.extend(getattr(self, '_import_errors', []))

        seen_ids = set()
        for k in self.knowledge_entries:
            if not k.id:
                errors.append("Knowledge entry missing id")
            elif k.id in seen_ids:
                errors.append(f"Duplicate knowledge id: {k.id}")
            seen_ids.add(k.id)

            if not k.title:
                errors.append(t("skf_error_missing_title", id=k.id))
            if not k.summary:
                errors.append(t("skf_error_missing_summary", id=k.id))
            if k.priority not in (0, 1, 2, 3):
                errors.append(t("skf_error_invalid_priority", id=k.id, priority=k.priority))

        for e in self.experience_log:
            if not e.event:
                errors.append(t("skf_error_missing_event", id=e.id))

        return errors

    def get_stats(self) -> dict:
        categories: dict[str, int] = {}
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

    # ``verify`` controls checksum compatibility only. Archive, schema,
    # content and evidence safety checks are mandatory for every import.
    errors = pkg.validate(check_checksums=verify)
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
        if not k.source_claim:
            k.source_claim = k.source
        if not k.verification_claim:
            k.verification_claim = k.verification
        k.source = "other_spark"
        # SKF is an untrusted transport.  Preserve the sender's claim only in
        # the package inspection layer; persisted knowledge starts unverified
        # until a local, auditable evidence workflow establishes otherwise.
        externalize_knowledge_evidence(k)
        k.verification = "unverified"
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
