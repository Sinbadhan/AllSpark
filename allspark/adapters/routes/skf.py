"""SKF and Verification API routes."""

from pathlib import Path

from fastapi import HTTPException, Query

from allspark.core.config import DEFAULT_DB_DIR
from allspark.services.skf_manager import SKFPackage, export_skf, import_skf

_SAFE_SKF_DIR = DEFAULT_DB_DIR / "skf"


def _safe_skf_path(path: str, *, must_exist: bool = False) -> str:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = _SAFE_SKF_DIR / candidate
    safe_root = _SAFE_SKF_DIR.resolve()
    resolved = candidate.resolve(strict=False)
    if safe_root != resolved and safe_root not in resolved.parents:
        raise HTTPException(400, "SKF paths must stay under ~/.allspark/skf")
    if must_exist and not resolved.exists():
        raise HTTPException(404, "SKF file not found")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return str(resolved)


def register_skf_routes(app, check):
    @app.get("/api/skf/info")
    async def skf_info(path: str = Query(...)):
        container, db = check()
        try:
            path = _safe_skf_path(path, must_exist=True)
            pkg = SKFPackage.import_from_file(path)
            return {"status": "ok", "stats": pkg.get_stats(), "validation_errors": pkg.validate()}
        except Exception as e:
            raise HTTPException(400, str(e))

    @app.post("/api/skf/export")
    async def skf_export(path: str = Query(...), category: str = Query(""), language: str = Query("")):
        container, db = check()
        try:
            path = _safe_skf_path(path)
            result = export_skf(db, path, category=category, language=language)
            return {"status": "ok", "path": result}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, str(e))

    @app.post("/api/skf/import")
    async def skf_import(path: str = Query(...), verify: bool = Query(True)):
        container, db = check()
        try:
            path = _safe_skf_path(path, must_exist=True)
            result = import_skf(db, path, verify=verify)
            if result["status"] == "validation_error":
                raise HTTPException(400, detail=result["errors"])
            return result
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, str(e))

    @app.get("/api/verify/stats")
    async def verify_stats():
        container, db = check()
        rows = db.conn.execute(
            "SELECT verification, COUNT(*) as cnt FROM knowledge GROUP BY verification"
        ).fetchall()
        return [{"level": r["verification"], "count": r["cnt"]} for r in rows]

    @app.post("/api/verify/entry")
    async def verify_entry(kid: str = Query(...)):
        container, db = check()
        entry = db.get_knowledge(kid)
        if not entry:
            raise HTTPException(404, "Entry not found")
        verifier = container.require("knowledge_verifier")
        report = verifier.verify_entry(entry)
        if entry.verification != report.level:
            entry.verification = report.level
            db.save_knowledge(entry)
        return report.to_dict()

    @app.post("/api/verify/batch")
    async def verify_batch(mode: str = Query("unverified")):
        container, db = check()
        if mode == "all":
            rows = db.conn.execute("SELECT * FROM knowledge").fetchall()
        else:
            rows = db.conn.execute("SELECT * FROM knowledge WHERE verification='unverified'").fetchall()
        entries = [db._row_to_entry(r) for r in rows]
        verifier = container.require("knowledge_verifier")
        reports = verifier.verify_batch(entries)
        for report in reports:
            entry = db.get_knowledge(report.entry_id)
            if entry and entry.verification != report.level:
                entry.verification = report.level
                db.save_knowledge(entry)
        return {"total": len(reports), "results": [r.to_dict() for r in reports]}
