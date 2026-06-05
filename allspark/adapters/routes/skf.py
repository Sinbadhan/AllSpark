"""SKF and Verification API routes."""

from fastapi import HTTPException, Query


def register_skf_routes(app, check):
    @app.get("/api/skf/info")
    async def skf_info(path: str = Query(...)):
        container, db = check()
        from allspark.services.skf_manager import SKFPackage
        try:
            pkg = SKFPackage.import_from_file(path)
            return {"status": "ok", "stats": pkg.get_stats(), "validation_errors": pkg.validate()}
        except Exception as e:
            raise HTTPException(400, str(e))

    @app.post("/api/skf/export")
    async def skf_export(path: str = Query(...), category: str = Query(""), language: str = Query("")):
        container, db = check()
        from allspark.services.skf_manager import export_skf
        try:
            result = export_skf(db, path, category=category, language=language)
            return {"status": "ok", "path": result}
        except Exception as e:
            raise HTTPException(500, str(e))

    @app.post("/api/skf/import")
    async def skf_import(path: str = Query(...), verify: bool = Query(True)):
        container, db = check()
        from allspark.services.skf_manager import import_skf
        try:
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
        from allspark.services.knowledge_verifier import KnowledgeVerifier
        entry = db.get_knowledge(kid)
        if not entry:
            raise HTTPException(404, "Entry not found")
        verifier = KnowledgeVerifier(db, container.get("llm"))
        report = verifier.verify_entry(entry)
        if entry.verification != report.level:
            entry.verification = report.level
            db.save_knowledge(entry)
        return report.to_dict()

    @app.post("/api/verify/batch")
    async def verify_batch(mode: str = Query("unverified")):
        container, db = check()
        from allspark.services.knowledge_verifier import KnowledgeVerifier
        if mode == "all":
            rows = db.conn.execute("SELECT * FROM knowledge").fetchall()
        else:
            rows = db.conn.execute("SELECT * FROM knowledge WHERE verification='unverified'").fetchall()
        entries = [db._row_to_entry(r) for r in rows]
        verifier = KnowledgeVerifier(db, container.get("llm"))
        reports = verifier.verify_batch(entries)
        for report in reports:
            entry = db.get_knowledge(report.entry_id)
            if entry and entry.verification != report.level:
                entry.verification = report.level
                db.save_knowledge(entry)
        return {"total": len(reports), "results": [r.to_dict() for r in reports]}
