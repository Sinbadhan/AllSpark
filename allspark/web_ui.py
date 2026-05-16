import json
import os
import urllib.request
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from allspark.database import Database
from allspark.rule_engine import RuleEngine
from allspark.resource_manager import ResourceManager
from allspark.knowledge_engine import KnowledgeEngine
from allspark.experience_engine import ExperienceEngine
from allspark.llm_engine import LLMEngine
from allspark.hardware import detect_hardware, compute_feature_flags, FeatureFlags
from allspark.module_loader import ModuleRegistry
from allspark.i18n import get_language, set_language, init_language
from allspark.config import DEFAULT_DB_DIR


class ChatRequest(BaseModel):
    message: str
    language: Optional[str] = None


class ExperienceRequest(BaseModel):
    event: str
    outcome: str
    lesson: str = ""


class ResourceUpdateRequest(BaseModel):
    type: str
    amount: float


MODELS_DIR = DEFAULT_DB_DIR / "models"

MODEL_DOWNLOAD_URLS = {
    "Qwen2.5-1.5B-Q4": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
    "Qwen2.5-3B-Q4": "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf",
    "Qwen2.5-7B-Q4": "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/qwen2.5-7b-instruct-q4_k_m.gguf",
    "Qwen2.5-14B-Q4": "https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF/resolve/main/qwen2.5-14b-instruct-q4_k_m.gguf",
    "Qwen2.5-32B-Q4": "https://huggingface.co/Qwen/Qwen2.5-32B-Instruct-GGUF/resolve/main/qwen2.5-32b-instruct-q4_k_m.gguf",
    "Qwen2.5-72B-Q4": "https://huggingface.co/Qwen/Qwen2.5-72B-Instruct-GGUF/resolve/main/qwen2.5-72b-instruct-q4_k_m.gguf",
}


def create_app(db_path: Optional[str] = None) -> FastAPI:
    app = FastAPI(title="ALLSPARK", version="0.2.0")

    db = Database(db_path)
    init_language(db)
    app.state.db = db
    app.state.engine = None
    app.state.initialized = db.is_initialized()

    if app.state.initialized:
        _load_engine(app)

    @app.get("/", response_class=HTMLResponse)
    async def index():
        if not app.state.initialized:
            return get_init_html()
        return get_index_html()

    @app.get("/api/init/status")
    async def init_status():
        return {"initialized": app.state.initialized}

    @app.get("/api/init/hardware")
    async def init_hardware():
        from allspark.hardware import detect_hardware, compute_feature_flags, HardwareTier, LLM_MODEL_MAP
        profile = detect_hardware()
        flags = compute_feature_flags(profile.tier, profile.gpu_available)
        model_info = LLM_MODEL_MAP.get(profile.tier, {})

        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        existing_models = [f.stem for f in MODELS_DIR.glob("*.gguf")]
        recommended_model = flags.llm_model
        model_downloaded = any(
            recommended_model.lower().replace("-", "").replace(".", "") in m.lower().replace("-", "").replace(".", "")
            for m in existing_models
        ) if existing_models else False

        return {
            "tier": profile.tier.value,
            "cpu_arch": profile.cpu_arch,
            "cpu_model": profile.cpu_model,
            "cpu_cores": profile.cpu_cores,
            "ram_total_gb": round(profile.ram_total_gb, 1),
            "ram_available_gb": round(profile.ram_available_gb, 1),
            "storage_total_gb": round(profile.storage_total_gb, 1),
            "storage_available_gb": round(profile.storage_available_gb, 1),
            "gpu_info": profile.gpu_info,
            "gpu_available": profile.gpu_available,
            "os_name": profile.os_name,
            "recommended_model": recommended_model,
            "model_size_gb": model_info.get("size_gb", 0),
            "model_speed_tps": model_info.get("speed_tps", ""),
            "model_downloaded": model_downloaded,
            "llm_enabled": flags.llm,
            "existing_models": existing_models,
        }

    @app.get("/api/init/models")
    async def init_list_models():
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        existing = []
        for f in MODELS_DIR.glob("*.gguf"):
            size_mb = f.stat().st_size / (1024 * 1024)
            existing.append({"name": f.stem, "filename": f.name, "size_mb": round(size_mb, 1)})
        downloadable = []
        for name, url in MODEL_DOWNLOAD_URLS.items():
            filename = url.split("/")[-1]
            exists = (MODELS_DIR / filename).exists()
            downloadable.append({"name": name, "url": url, "filename": filename, "downloaded": exists})
        return {"existing": existing, "downloadable": downloadable}

    @app.post("/api/init/download")
    async def init_download_model(model_name: str = Query(...)):
        url = MODEL_DOWNLOAD_URLS.get(model_name)
        if not url:
            raise HTTPException(400, f"Unknown model: {model_name}")
        filename = url.split("/")[-1]
        dest = MODELS_DIR / filename
        MODELS_DIR.mkdir(parents=True, exist_ok=True)

        if dest.exists():
            return {"status": "already_exists", "path": str(dest)}

        try:
            import threading

            def _download():
                tmp = dest.with_suffix(".tmp")
                urllib.request.urlretrieve(url, str(tmp))
                tmp.rename(dest)

            t = threading.Thread(target=_download, daemon=True)
            t.start()
            return {"status": "downloading", "model": model_name, "path": str(dest)}
        except Exception as e:
            raise HTTPException(500, f"Download failed: {e}")

    @app.get("/api/init/download_progress")
    async def init_download_progress(model_name: str = Query(...)):
        url = MODEL_DOWNLOAD_URLS.get(model_name, "")
        filename = url.split("/")[-1]
        dest = MODELS_DIR / filename
        tmp = dest.with_suffix(".tmp")

        if dest.exists():
            return {"status": "done", "path": str(dest)}
        if tmp.exists():
            current_size = tmp.stat().st_size
            return {"status": "downloading", "current_bytes": current_size}
        return {"status": "not_started"}

    @app.post("/api/init/complete")
    async def init_complete(
        language: str = Query("zh"),
        survivor_name: str = Query("Survivor"),
        skip_model: bool = Query(False),
    ):
        from allspark.hardware import detect_hardware, compute_feature_flags
        from allspark.module_loader import ModuleRegistry
        from allspark.i18n import set_language

        db = app.state.db
        profile = detect_hardware()
        flags = compute_feature_flags(profile.tier, profile.gpu_available)

        for key, val in [
            ("cpu_arch", profile.cpu_arch), ("cpu_model", profile.cpu_model),
            ("cpu_cores", str(profile.cpu_cores)),
            ("ram_total_gb", f"{profile.ram_total_gb:.1f}"),
            ("ram_available_gb", f"{profile.ram_available_gb:.1f}"),
            ("storage_total_gb", f"{profile.storage_total_gb:.1f}"),
            ("storage_available_gb", f"{profile.storage_available_gb:.1f}"),
            ("gpu_info", profile.gpu_info),
            ("gpu_available", str(profile.gpu_available)),
            ("os_name", profile.os_name), ("os_version", profile.os_version),
            ("tier", profile.tier.value),
        ]:
            db.save_hardware_profile(key, val)

        registry = ModuleRegistry(flags)
        registry.save_to_db(db)

        set_language(language)
        db.save_survivor_state("name", survivor_name)
        db.save_survivor_state("language", language)
        db.mark_initialized()

        app.state.initialized = True
        _load_engine(app)

        return {"status": "ok"}

    _register_api_routes(app)

    return app


def _load_engine(app):
    db = app.state.db
    from allspark.hardware import detect_hardware, compute_feature_flags
    from allspark.module_loader import ModuleRegistry

    registry_loaded = ModuleRegistry.load_from_db(db)
    if registry_loaded:
        flags = registry_loaded.flags
    else:
        profile = detect_hardware()
        flags = compute_feature_flags(profile.tier, profile.gpu_available)

    engine = RuleEngine(db, flags=flags)
    engine.initialize()
    app.state.engine = engine


def _require_init(app):
    def _check():
        if not app.state.initialized or not app.state.engine:
            raise HTTPException(503, "AllSpark not initialized. Complete setup first.")
        return app.state.engine, app.state.db
    return _check


def _get_or_create(app, attr: str, factory):
    if not hasattr(app.state, attr) or getattr(app.state, attr) is None:
        setattr(app.state, attr, factory())
    return getattr(app.state, attr)


def _register_api_routes(app):
    check = _require_init(app)

    @app.get("/api/status")
    async def get_status():
        engine, db = check()
        assessment = engine.survival.assess()
        mode, _ = engine.resource_mgr.update_operating_mode()
        warnings = engine.resource_mgr.check_warnings()
        resources = engine.resource_mgr.get_all_resources()
        exp_stats = engine.experience.get_stats()
        llm_status = engine.llm.get_status()

        return {
            "phase": assessment["phase"],
            "phase_name": assessment.get("phase_name", ""),
            "mode": mode.value if hasattr(mode, "value") else str(mode),
            "warnings": warnings,
            "resources": [
                {
                    "type": r.type.value,
                    "amount": r.current_amount,
                    "unit": r.unit,
                    "daily_consumption": r.daily_consumption,
                    "daily_intake": r.daily_intake,
                    "remaining_hours": r.estimated_remaining_hours,
                    "offline": r.current_amount == 0 and r.daily_consumption == 0,
                }
                for r in resources
            ],
            "experience": exp_stats,
            "llm": llm_status,
            "modules": engine.registry.format_status_dict(),
        }

    @app.get("/api/resources")
    async def get_resources():
        engine, db = check()
        resources = engine.resource_mgr.get_all_resources()
        return [
            {
                "type": r.type.value,
                "amount": r.current_amount,
                "unit": r.unit,
                "daily_consumption": r.daily_consumption,
                "daily_intake": r.daily_intake,
                "remaining_hours": r.estimated_remaining_hours,
                "offline": r.current_amount == 0 and r.daily_consumption == 0,
            }
            for r in resources
        ]

    @app.post("/api/resources")
    async def update_resource(req: ResourceUpdateRequest):
        engine, db = check()
        from allspark.models import ResourceType
        try:
            rtype = ResourceType(req.type)
        except ValueError:
            raise HTTPException(400, f"Invalid resource type: {req.type}")
        engine.resource_mgr.update_resource(rtype, req.amount)
        return {"status": "ok"}

    @app.get("/api/knowledge/search")
    async def search_knowledge(q: str = Query(..., min_length=1), limit: int = 10):
        engine, db = check()
        if engine.knowledge:
            entries = engine.knowledge.search_by_language(q, limit)
            return [
                {
                    "id": e.id,
                    "category": e.category,
                    "subcategory": e.subcategory,
                    "priority": e.priority,
                    "title": e.title,
                    "summary": e.summary,
                    "steps": e.steps,
                    "warnings": e.warnings,
                    "verification": e.verification,
                    "source": e.source,
                }
                for e in entries
            ]
        return []

    @app.get("/api/knowledge/categories")
    async def get_categories():
        engine, db = check()
        if engine.knowledge:
            cats = engine.knowledge.get_categories()
            result = []
            for cat in cats:
                subs = engine.knowledge.get_subcategories(cat)
                result.append({"category": cat, "subcategories": subs})
            return result
        return []

    @app.get("/api/knowledge/category/{category}")
    async def get_by_category(category: str, subcategory: str = ""):
        engine, db = check()
        if engine.knowledge:
            entries = engine.knowledge.get_by_category(category, subcategory)
            return [
                {
                    "id": e.id,
                    "title": e.title,
                    "summary": e.summary,
                    "priority": e.priority,
                }
                for e in entries
            ]
        return []

    @app.get("/api/knowledge/{kid}")
    async def get_knowledge_entry(kid: str):
        engine, db = check()
        entry = db.get_knowledge(kid)
        if not entry:
            raise HTTPException(404, "Knowledge entry not found")
        return {
            "id": entry.id,
            "category": entry.category,
            "subcategory": entry.subcategory,
            "priority": entry.priority,
            "title": entry.title,
            "summary": entry.summary,
            "steps": entry.steps,
            "prerequisites": entry.prerequisites,
            "warnings": entry.warnings,
            "verification": entry.verification,
            "source": entry.source,
            "language": entry.language,
        }

    @app.post("/api/chat")
    async def chat(req: ChatRequest):
        engine, db = check()
        if req.language:
            set_language(req.language)
        response = engine.process_input(req.message)
        return {"response": response}

    @app.get("/api/experience")
    async def get_experiences(limit: int = 20):
        engine, db = check()
        entries = engine.experience.get_recent(limit)
        return [
            {
                "id": e.id,
                "timestamp": e.timestamp,
                "event": e.event,
                "outcome": e.outcome,
                "lesson": e.lesson,
                "promoted": bool(e.related_knowledge_id),
            }
            for e in entries
        ]

    @app.post("/api/experience")
    async def log_experience(req: ExperienceRequest):
        engine, db = check()
        entry = engine.experience.log(
            event=req.event, outcome=req.outcome, lesson=req.lesson
        )
        return {"id": entry.id, "status": "ok"}

    @app.get("/api/experience/patterns")
    async def get_patterns():
        engine, db = check()
        return engine.experience.get_patterns()

    @app.get("/api/llm/status")
    async def get_llm_status():
        engine, db = check()
        return engine.llm.get_status()

    @app.post("/api/llm/load")
    async def load_llm():
        engine, db = check()
        ok = engine.llm.load()
        if ok:
            engine.registry.register("llm", engine.llm)
            engine.registry.save_to_db(db)
            return {"status": "ok", "model": engine.llm.model_name}
        return {"status": "error", "error": engine.llm.error}

    @app.get("/api/tasks")
    async def get_tasks():
        engine, db = check()
        active = db.get_active_tasks()
        return [
            {
                "id": t.id,
                "phase": t.phase,
                "priority": t.priority,
                "title": t.title,
                "description": t.description,
                "status": t.status,
            }
            for t in active
        ]

    @app.get("/api/modules")
    async def get_modules():
        engine, db = check()
        return engine.registry.format_status_dict()

    # --- Phase 3: SKF / Verification / Network / Vision ---

    @app.get("/api/skf/info")
    async def skf_info(path: str = Query(...)):
        engine, db = check()
        from allspark.skf_manager import SKFPackage
        try:
            pkg = SKFPackage.import_from_file(path)
            return {"status": "ok", "stats": pkg.get_stats(), "validation_errors": pkg.validate()}
        except Exception as e:
            raise HTTPException(400, str(e))

    @app.post("/api/skf/export")
    async def skf_export(path: str = Query(...), category: str = Query(""), language: str = Query("")):
        engine, db = check()
        from allspark.skf_manager import export_skf
        try:
            result = export_skf(db, path, category=category, language=language)
            return {"status": "ok", "path": result}
        except Exception as e:
            raise HTTPException(500, str(e))

    @app.post("/api/skf/import")
    async def skf_import(path: str = Query(...), verify: bool = Query(True)):
        engine, db = check()
        from allspark.skf_manager import import_skf
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
        engine, db = check()
        rows = db.conn.execute(
            "SELECT verification, COUNT(*) as cnt FROM knowledge GROUP BY verification"
        ).fetchall()
        return [{"level": r["verification"], "count": r["cnt"]} for r in rows]

    @app.post("/api/verify/entry")
    async def verify_entry(kid: str = Query(...)):
        engine, db = check()
        from allspark.knowledge_verifier import KnowledgeVerifier
        entry = db.get_knowledge(kid)
        if not entry:
            raise HTTPException(404, "Entry not found")
        verifier = KnowledgeVerifier(db, engine.llm)
        report = verifier.verify_entry(entry)
        if entry.verification != report.level:
            entry.verification = report.level
            db.save_knowledge(entry)
        return report.to_dict()

    @app.post("/api/verify/batch")
    async def verify_batch(mode: str = Query("unverified")):
        engine, db = check()
        from allspark.knowledge_verifier import KnowledgeVerifier
        if mode == "all":
            rows = db.conn.execute("SELECT * FROM knowledge").fetchall()
        else:
            rows = db.conn.execute("SELECT * FROM knowledge WHERE verification='unverified'").fetchall()
        entries = [db._row_to_entry(r) for r in rows]
        verifier = KnowledgeVerifier(db, engine.llm)
        reports = verifier.verify_batch(entries)
        for report in reports:
            entry = db.get_knowledge(report.entry_id)
            if entry and entry.verification != report.level:
                entry.verification = report.level
                db.save_knowledge(entry)
        return {"total": len(reports), "results": [r.to_dict() for r in reports]}

    @app.get("/api/network/status")
    async def network_status():
        engine, db = check()
        _get_or_create(app, 'network', lambda: __import__('allspark.spark_network', fromlist=['SparkNetwork']).SparkNetwork(db=db, llm_engine=engine.llm))
        return app.state.network.get_status()

    @app.post("/api/network/scan")
    async def network_scan():
        engine, db = check()
        _get_or_create(app, 'network', lambda: __import__('allspark.spark_network', fromlist=['SparkNetwork']).SparkNetwork(db=db, llm_engine=engine.llm))
        return app.state.network.detect_channels()

    @app.post("/api/network/start")
    async def network_start():
        engine, db = check()
        _get_or_create(app, 'network', lambda: __import__('allspark.spark_network', fromlist=['SparkNetwork']).SparkNetwork(db=db, llm_engine=engine.llm))
        result = app.state.network.start_discovery()
        if result["status"] == "started":
            app.state.network.start_exchange_server()
        return result

    @app.post("/api/network/stop")
    async def network_stop():
        if hasattr(app.state, 'network') and app.state.network:
            return app.state.network.stop_discovery()
        return {"status": "not_running"}

    @app.post("/api/network/exchange")
    async def network_exchange(node_id: str = Query(...)):
        if hasattr(app.state, 'network') and app.state.network:
            return app.state.network.request_exchange(node_id)
        return {"status": "error", "message": "Network not started"}

    @app.post("/api/network/send")
    async def network_send(node_id: str = Query(...), entry_ids: str = Query(...)):
        if hasattr(app.state, 'network') and app.state.network:
            ids = [x.strip() for x in entry_ids.split(",")]
            return app.state.network.send_knowledge(node_id, ids)
        return {"status": "error", "message": "Network not started"}

    @app.get("/api/vision/status")
    async def vision_status():
        engine, db = check()
        _get_or_create(app, 'vision', lambda: __import__('allspark.vision_engine', fromlist=['VisionEngine']).VisionEngine(llm_engine=engine.llm, db=db))
        return app.state.vision.get_status()

    @app.post("/api/vision/analyze")
    async def vision_analyze(
        image_path: str = Query(...),
        task: str = Query("general"),
    ):
        engine, db = check()
        _get_or_create(app, 'vision', lambda: __import__('allspark.vision_engine', fromlist=['VisionEngine']).VisionEngine(llm_engine=engine.llm, db=db))
        from allspark.vision_engine import VisionTask
        try:
            vtask = VisionTask(task)
        except ValueError:
            vtask = VisionTask.GENERAL
        result = app.state.vision.analyze_image(image_path, vtask)
        return result.to_dict()

    # --- Phase 4: Governance / Trade ---

    @app.get("/api/governance/status")
    async def governance_status():
        engine, db = check()
        _get_or_create(app, 'gov', lambda: __import__('allspark.governance', fromlist=['GovernanceEngine']).GovernanceEngine(db=db, llm_engine=engine.llm))
        return app.state.gov.get_status()

    @app.post("/api/governance/member/add")
    async def governance_member_add(
        name: str = Query(...),
        role: str = Query("executor"),
        domains: str = Query(""),
    ):
        engine, db = check()
        _get_or_create(app, 'gov', lambda: __import__('allspark.governance', fromlist=['GovernanceEngine']).GovernanceEngine(db=db, llm_engine=engine.llm))
        domain_list = [d.strip() for d in domains.split(",") if d.strip()] if domains else []
        member = app.state.gov.add_member(name, role=role, domains=domain_list)
        return {"status": "ok", "member": {"id": member.id, "name": member.name, "role": member.role, "is_commander": member.is_commander}}

    @app.post("/api/governance/member/remove")
    async def governance_member_remove(member_id: str = Query(...)):
        engine, db = check()
        _get_or_create(app, 'gov', lambda: __import__('allspark.governance', fromlist=['GovernanceEngine']).GovernanceEngine(db=db, llm_engine=engine.llm))
        if app.state.gov.remove_member(member_id):
            return {"status": "ok"}
        return {"status": "error", "message": "Cannot remove member"}

    @app.post("/api/governance/member/role")
    async def governance_member_role(
        member_id: str = Query(...),
        role: str = Query(...),
        domains: str = Query(""),
    ):
        engine, db = check()
        _get_or_create(app, 'gov', lambda: __import__('allspark.governance', fromlist=['GovernanceEngine']).GovernanceEngine(db=db, llm_engine=engine.llm))
        domain_list = [d.strip() for d in domains.split(",") if d.strip()] if domains else None
        if app.state.gov.assign_role(member_id, role, domain_list):
            return {"status": "ok"}
        return {"status": "error", "message": "Cannot assign role"}

    @app.get("/api/governance/members")
    async def governance_members():
        engine, db = check()
        _get_or_create(app, 'gov', lambda: __import__('allspark.governance', fromlist=['GovernanceEngine']).GovernanceEngine(db=db, llm_engine=engine.llm))
        members = app.state.gov.get_all_members()
        return {"members": [
            {"id": m.id, "name": m.name, "role": m.role, "domains": m.domains,
             "skills": m.skills, "health_status": m.health_status,
             "psychological_stability": m.psychological_stability,
             "contribution_score": m.contribution_score,
             "is_commander": m.is_commander}
            for m in members
        ]}

    @app.get("/api/governance/assess")
    async def governance_assess():
        engine, db = check()
        _get_or_create(app, 'gov', lambda: __import__('allspark.governance', fromlist=['GovernanceEngine']).GovernanceEngine(db=db, llm_engine=engine.llm))
        return app.state.gov.assess_organization()

    @app.get("/api/governance/recommend")
    async def governance_recommend():
        engine, db = check()
        _get_or_create(app, 'gov', lambda: __import__('allspark.governance', fromlist=['GovernanceEngine']).GovernanceEngine(db=db, llm_engine=engine.llm))
        return {"recommendations": app.state.gov.recommend_roles()}

    @app.get("/api/governance/survival-value")
    async def governance_survival_value(member_id: str = Query(...)):
        engine, db = check()
        _get_or_create(app, 'gov', lambda: __import__('allspark.governance', fromlist=['GovernanceEngine']).GovernanceEngine(db=db, llm_engine=engine.llm))
        result = app.state.gov.calculate_survival_value(member_id)
        if not result:
            return {"status": "error", "message": "Member not found"}
        return result

    @app.post("/api/governance/conflict/create")
    async def governance_conflict_create(
        title: str = Query(...),
        parties: str = Query(...),
    ):
        engine, db = check()
        _get_or_create(app, 'gov', lambda: __import__('allspark.governance', fromlist=['GovernanceEngine']).GovernanceEngine(db=db, llm_engine=engine.llm))
        party_list = [p.strip() for p in parties.split(",") if p.strip()]
        conflict = app.state.gov.create_conflict(title, "", party_list)
        return {"status": "ok", "conflict_id": conflict.id}

    @app.post("/api/governance/conflict/mediate")
    async def governance_conflict_mediate(conflict_id: str = Query(...)):
        engine, db = check()
        _get_or_create(app, 'gov', lambda: __import__('allspark.governance', fromlist=['GovernanceEngine']).GovernanceEngine(db=db, llm_engine=engine.llm))
        result = app.state.gov.mediate_conflict(conflict_id)
        if not result:
            return {"status": "error", "message": "Conflict not found"}
        return result

    @app.post("/api/governance/conflict/resolve")
    async def governance_conflict_resolve(
        conflict_id: str = Query(...),
        resolution: str = Query("Resolved"),
    ):
        engine, db = check()
        _get_or_create(app, 'gov', lambda: __import__('allspark.governance', fromlist=['GovernanceEngine']).GovernanceEngine(db=db, llm_engine=engine.llm))
        if app.state.gov.resolve_conflict(conflict_id, resolution):
            return {"status": "ok"}
        return {"status": "error", "message": "Cannot resolve conflict"}

    @app.get("/api/governance/conflicts")
    async def governance_conflicts():
        engine, db = check()
        _get_or_create(app, 'gov', lambda: __import__('allspark.governance', fromlist=['GovernanceEngine']).GovernanceEngine(db=db, llm_engine=engine.llm))
        conflicts = app.state.gov.get_all_conflicts()
        return {"conflicts": [
            {"id": c.id, "title": c.title, "parties": c.parties,
             "status": c.status, "mediator": c.mediator,
             "resolution": c.resolution, "created_at": c.created_at,
             "resolved_at": c.resolved_at}
            for c in conflicts
        ]}

    @app.get("/api/trade/status")
    async def trade_status():
        engine, db = check()
        _get_or_create(app, 'trade', lambda: __import__('allspark.trade_engine', fromlist=['TradeEngine']).TradeEngine(db=db))
        return app.state.trade.get_status()

    @app.post("/api/trade/propose")
    async def trade_propose(
        target_spark_id: str = Query(...),
        offer_ids: str = Query(""),
        request_ids: str = Query(""),
    ):
        engine, db = check()
        _get_or_create(app, 'trade', lambda: __import__('allspark.trade_engine', fromlist=['TradeEngine']).TradeEngine(db=db))
        offer_list = [i.strip() for i in offer_ids.split(",") if i.strip()] if offer_ids else []
        request_list = [i.strip() for i in request_ids.split(",") if i.strip()] if request_ids else []
        offer = app.state.trade.propose_trade("local", target_spark_id, offer_list, request_list)
        return {"status": "ok", "trade_id": offer.id}

    @app.post("/api/trade/accept")
    async def trade_accept(trade_id: str = Query(...)):
        engine, db = check()
        _get_or_create(app, 'trade', lambda: __import__('allspark.trade_engine', fromlist=['TradeEngine']).TradeEngine(db=db))
        return app.state.trade.accept_trade(trade_id)

    @app.post("/api/trade/reject")
    async def trade_reject(trade_id: str = Query(...)):
        engine, db = check()
        _get_or_create(app, 'trade', lambda: __import__('allspark.trade_engine', fromlist=['TradeEngine']).TradeEngine(db=db))
        if app.state.trade.reject_trade(trade_id):
            return {"status": "ok"}
        return {"status": "error", "message": "Trade not found"}

    @app.get("/api/trade/evaluate")
    async def trade_evaluate(trade_id: str = Query(...)):
        engine, db = check()
        _get_or_create(app, 'trade', lambda: __import__('allspark.trade_engine', fromlist=['TradeEngine']).TradeEngine(db=db))
        result = app.state.trade.evaluate_trade(trade_id)
        if not result:
            return {"status": "error", "message": "Trade not found"}
        return result

    @app.get("/api/trade/list")
    async def trade_list():
        engine, db = check()
        _get_or_create(app, 'trade', lambda: __import__('allspark.trade_engine', fromlist=['TradeEngine']).TradeEngine(db=db))
        trades = app.state.trade.get_active_trades()
        return {"trades": [
            {"id": t.id, "target": t.target_spark_id,
             "offer_ids": t.offer_knowledge_ids,
             "request_ids": t.request_knowledge_ids,
             "status": t.status, "created_at": t.created_at}
            for t in trades
        ]}

    # --- Phase 5: Power / Sensors / Preservation ---

    @app.get("/api/power/status")
    async def power_status():
        engine, db = check()
        _get_or_create(app, 'power_monitor', lambda: __import__('allspark.power_monitor', fromlist=['PowerMonitor']).PowerMonitor(db=db))
        return app.state.power_monitor.get_status()

    @app.post("/api/power/monitor/start")
    async def power_monitor_start(interval: int = Query(60)):
        engine, db = check()
        _get_or_create(app, 'power_monitor', lambda: __import__('allspark.power_monitor', fromlist=['PowerMonitor']).PowerMonitor(db=db))
        return app.state.power_monitor.start_monitoring(interval)

    @app.post("/api/power/monitor/stop")
    async def power_monitor_stop():
        engine, db = check()
        _get_or_create(app, 'power_monitor', lambda: __import__('allspark.power_monitor', fromlist=['PowerMonitor']).PowerMonitor(db=db))
        return app.state.power_monitor.stop_monitoring()

    @app.post("/api/power/manual")
    async def power_manual(
        energy_wh: float = Query(...),
        charging: bool = Query(False),
    ):
        engine, db = check()
        _get_or_create(app, 'power_monitor', lambda: __import__('allspark.power_monitor', fromlist=['PowerMonitor']).PowerMonitor(db=db))
        return app.state.power_monitor.manual_input(energy_wh, charging)

    @app.get("/api/power/runtime")
    async def power_runtime():
        engine, db = check()
        _get_or_create(app, 'power_monitor', lambda: __import__('allspark.power_monitor', fromlist=['PowerMonitor']).PowerMonitor(db=db))
        return app.state.power_monitor.estimate_runtime()

    @app.get("/api/power/history")
    async def power_history(last_n: int = Query(100)):
        engine, db = check()
        _get_or_create(app, 'power_monitor', lambda: __import__('allspark.power_monitor', fromlist=['PowerMonitor']).PowerMonitor(db=db))
        return {"readings": app.state.power_monitor.get_history(last_n)}

    @app.get("/api/sensor/status")
    async def sensor_status():
        engine, db = check()
        _get_or_create(app, 'sensor_hub', lambda: __import__('allspark.sensor_hub', fromlist=['SensorHub']).SensorHub(db=db))
        return app.state.sensor_hub.get_status()

    @app.get("/api/sensor/devices")
    async def sensor_devices():
        engine, db = check()
        _get_or_create(app, 'sensor_hub', lambda: __import__('allspark.sensor_hub', fromlist=['SensorHub']).SensorHub(db=db))
        return {"devices": app.state.sensor_hub.get_all_devices()}

    @app.post("/api/sensor/device/add")
    async def sensor_device_add(
        name: str = Query(...),
        sensor_type: str = Query("temperature"),
    ):
        engine, db = check()
        _get_or_create(app, 'sensor_hub', lambda: __import__('allspark.sensor_hub', fromlist=['SensorHub']).SensorHub(db=db))
        device = app.state.sensor_hub.register_device(name, sensor_type)
        return {"status": "ok", "device": {"name": device.name, "type": device.sensor_type, "interface": device.interface}}

    @app.post("/api/sensor/poll/start")
    async def sensor_poll_start():
        engine, db = check()
        _get_or_create(app, 'sensor_hub', lambda: __import__('allspark.sensor_hub', fromlist=['SensorHub']).SensorHub(db=db))
        return app.state.sensor_hub.start_polling()

    @app.post("/api/sensor/poll/stop")
    async def sensor_poll_stop():
        engine, db = check()
        _get_or_create(app, 'sensor_hub', lambda: __import__('allspark.sensor_hub', fromlist=['SensorHub']).SensorHub(db=db))
        return app.state.sensor_hub.stop_polling()

    @app.get("/api/sensor/snapshot")
    async def sensor_snapshot():
        engine, db = check()
        _get_or_create(app, 'sensor_hub', lambda: __import__('allspark.sensor_hub', fromlist=['SensorHub']).SensorHub(db=db))
        snap = app.state.sensor_hub.get_snapshot()
        return {
            "timestamp": snap.timestamp,
            "temperature_c": snap.temperature_c,
            "humidity_pct": snap.humidity_pct,
            "pressure_hpa": snap.pressure_hpa,
            "latitude": snap.latitude,
            "longitude": snap.longitude,
            "altitude_m": snap.altitude_m,
            "light_lux": snap.light_lux,
            "air_quality_ppm": snap.air_quality_ppm,
            "water_level_cm": snap.water_level_cm,
        }

    @app.get("/api/sensor/detect")
    async def sensor_detect():
        engine, db = check()
        _get_or_create(app, 'sensor_hub', lambda: __import__('allspark.sensor_hub', fromlist=['SensorHub']).SensorHub(db=db))
        return {"detected": app.state.sensor_hub.auto_detect()}

    @app.get("/api/preserve/status")
    async def preserve_status():
        engine, db = check()
        _get_or_create(app, 'preserve', lambda: __import__('allspark.data_preservation', fromlist=['DataPreservation']).DataPreservation(db=db))
        return app.state.preserve.get_status()

    @app.post("/api/preserve/auto-save/start")
    async def preserve_auto_start(interval: int = Query(300)):
        engine, db = check()
        _get_or_create(app, 'preserve', lambda: __import__('allspark.data_preservation', fromlist=['DataPreservation']).DataPreservation(db=db))
        return app.state.preserve.start_auto_save(interval)

    @app.post("/api/preserve/auto-save/stop")
    async def preserve_auto_stop():
        engine, db = check()
        _get_or_create(app, 'preserve', lambda: __import__('allspark.data_preservation', fromlist=['DataPreservation']).DataPreservation(db=db))
        return app.state.preserve.stop_auto_save()

    @app.post("/api/preserve/emergency")
    async def preserve_emergency():
        engine, db = check()
        _get_or_create(app, 'preserve', lambda: __import__('allspark.data_preservation', fromlist=['DataPreservation']).DataPreservation(db=db))
        return app.state.preserve.emergency_save("web_api")

    @app.post("/api/preserve/snapshot")
    async def preserve_snapshot(label: str = Query("")):
        engine, db = check()
        _get_or_create(app, 'preserve', lambda: __import__('allspark.data_preservation', fromlist=['DataPreservation']).DataPreservation(db=db))
        return app.state.preserve.create_snapshot(label)

    @app.get("/api/preserve/snapshots")
    async def preserve_snapshots():
        engine, db = check()
        _get_or_create(app, 'preserve', lambda: __import__('allspark.data_preservation', fromlist=['DataPreservation']).DataPreservation(db=db))
        return {"snapshots": app.state.preserve.list_snapshots()}



# ============================================================
# Phase 7 API Endpoints
# ============================================================

@app.get("/api/goals")
async def api_goals():
    """获取所有活跃目标"""
    if not hasattr(app.state, 'goal_engine') or app.state.goal_engine is None:
        return {"error": "Goal engine not loaded", "goals": []}
    goals = app.state.goal_engine.get_active_goals()
    return {"goals": [
        {
            "id": g.id, "title": g.title, "description": g.description,
            "priority": g.priority, "status": g.status, "progress": g.progress,
            "category": g.category, "milestone_done": g.milestone_done,
            "milestone_count": g.milestone_count, "deadline": g.deadline,
        } for g in goals
    ]}

@app.get("/api/goals/{goal_id}")
async def api_goal_detail(goal_id: str):
    """获取目标详情"""
    if not hasattr(app.state, 'goal_engine') or app.state.goal_engine is None:
        return {"error": "Goal engine not loaded"}
    goal = app.state.goal_engine.get_goal(goal_id)
    if not goal:
        return {"error": "Goal not found"}
    milestones = app.state.goal_engine.get_milestones(goal_id)
    return {
        "goal": {
            "id": goal.id, "title": goal.title, "description": goal.description,
            "priority": goal.priority, "status": goal.status, "progress": goal.progress,
            "category": goal.category, "source": goal.source,
            "milestone_done": goal.milestone_done, "milestone_count": goal.milestone_count,
            "deadline": goal.deadline, "rationale": goal.rationale,
        },
        "milestones": [
            {"id": m.id, "description": m.description, "done": m.done, "order": m.order}
            for m in milestones
        ],
    }

@app.post("/api/goals/add")
async def api_add_goal(request: Request):
    """手动添加目标"""
    if not hasattr(app.state, 'goal_engine') or app.state.goal_engine is None:
        return {"error": "Goal engine not loaded"}
    data = await request.json()
    goal = app.state.goal_engine.add_manual_goal(
        title=data.get("title", ""),
        description=data.get("description", ""),
        priority=data.get("priority", "medium"),
        category=data.get("category", "survival"),
    )
    return {"goal": {"id": goal.id, "title": goal.title}}

@app.post("/api/goals/{goal_id}/complete")
async def api_complete_goal(goal_id: str):
    """完成目标"""
    if not hasattr(app.state, 'goal_engine') or app.state.goal_engine is None:
        return {"error": "Goal engine not loaded"}
    success = app.state.goal_engine.complete_goal(goal_id)
    return {"success": success}

@app.post("/api/milestones/{milestone_id}/complete")
async def api_complete_milestone(milestone_id: str):
    """完成里程碑"""
    if not hasattr(app.state, 'goal_engine') or app.state.goal_engine is None:
        return {"error": "Goal engine not loaded"}
    success = app.state.goal_engine.complete_milestone(milestone_id)
    return {"success": success}

@app.get("/api/briefing")
async def api_briefing():
    """获取每日简报"""
    if not hasattr(app.state, 'daily_briefing') or app.state.daily_briefing is None:
        return {"error": "Briefing module not loaded"}
    briefing = app.state.daily_briefing.generate()
    return {"briefing": briefing}

@app.get("/api/briefing/short")
async def api_briefing_short():
    """获取简化版简报"""
    if not hasattr(app.state, 'daily_briefing') or app.state.daily_briefing is None:
        return {"error": "Briefing module not loaded"}
    briefing = app.state.daily_briefing.generate_short()
    return {"briefing": briefing}

@app.get("/api/timeline")
async def api_timeline(day: int = None, limit: int = 50):
    """获取时间线"""
    if not hasattr(app.state, 'timeline') or app.state.timeline is None:
        return {"error": "Timeline module not loaded"}
    events = app.state.timeline.get_events(day=day, limit=limit)
    return {"events": [
        {
            "id": e.id, "day": e.day, "timestamp": e.timestamp,
            "event_type": e.event_type, "title": e.title,
            "description": e.description, "emotion": e.emotion,
        } for e in events
    ]}

@app.get("/api/timeline/recent")
async def api_timeline_recent(days: int = 7):
    """获取最近N天的时间线"""
    if not hasattr(app.state, 'timeline') or app.state.timeline is None:
        return {"error": "Timeline module not loaded"}
    text = app.state.timeline.format_recent(days=days)
    return {"timeline": text}

@app.get("/api/diary")
async def api_diary(date: str = None):
    """获取日记"""
    if not hasattr(app.state, 'diary') or app.state.diary is None:
        return {"error": "Diary module not loaded"}
    if date:
        entries = app.state.diary.get_by_date(date)
    else:
        latest = app.state.diary.get_latest()
        entries = [latest] if latest else []
    return {"entries": [
        {
            "id": e.id, "date": e.date, "content": e.content,
            "emotion": e.emotion, "keywords": e.keywords,
        } for e in entries
    ]}

@app.post("/api/diary/add")
async def api_add_diary(request: Request):
    """添加日记"""
    if not hasattr(app.state, 'diary') or app.state.diary is None:
        return {"error": "Diary module not loaded"}
    data = await request.json()
    entry = app.state.diary.create_entry(
        content=data.get("content", ""),
        related_goal_id=data.get("related_goal_id", ""),
    )
    return {"entry": {"id": entry.id, "date": entry.date}}

@app.get("/api/diary/review")
async def api_diary_review(days: int = 7):
    """日记回顾"""
    if not hasattr(app.state, 'diary') or app.state.diary is None:
        return {"error": "Diary module not loaded"}
    from datetime import datetime, timedelta
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    entries = app.state.diary.get_range(start_date, end_date)
    text = app.state.diary.format_review(entries, days=days)
    return {"review": text}

@app.get("/api/gps")
async def api_gps():
    """获取 GPS 位置"""
    if not hasattr(app.state, 'gps_manager') or app.state.gps_manager is None:
        return {"error": "GPS module not loaded", "location": None}
    loc = app.state.gps_manager.get_location()
    return {"location": loc}

@app.post("/api/gps/set")
async def api_set_gps(request: Request):
    """设置 GPS 位置"""
    if not hasattr(app.state, 'gps_manager') or app.state.gps_manager is None:
        return {"error": "GPS module not loaded"}
    data = await request.json()
    lat = data.get("latitude", 0)
    lon = data.get("longitude", 0)
    alt = data.get("altitude", 0)
    app.state.gps_manager.set_location(lat, lon, alt)
    return {"success": True, "location": app.state.gps_manager.get_location()}

@app.get("/api/gps/nearby")
async def api_gps_nearby(radius_km: float = 5.0):
    """获取附近 POI"""
    if not hasattr(app.state, 'gps_manager') or app.state.gps_manager is None:
        return {"error": "GPS module not loaded", "nearby": []}
    nearby = app.state.gps_manager.get_nearby_pois(radius_km=radius_km)
    return {"nearby": [
        {
            "poi": {"id": item["poi"].id, "name": item["poi"].name, "type": item["poi"].type},
            "distance_km": item["distance_km"],
        } for item in nearby
    ]}

@app.post("/api/reset/{level}")
async def api_reset(level: int, request: Request):
    """执行系统重置"""
    if not hasattr(app.state, 'reset_manager') or app.state.reset_manager is None:
        return {"error": "Reset manager not loaded"}
    data = await request.json()
    confirm = data.get("confirm", False)
    if not confirm:
        return {"error": "Confirmation required. Send confirm=true"}
    
    if level == 1:
        result = app.state.reset_manager.reset_assessment()
    elif level == 2:
        result = app.state.reset_manager.reset_archive()
    elif level == 3:
        password = data.get("password", "")
        result = app.state.reset_manager.reset_factory(password)
    else:
        return {"error": "Invalid reset level (1/2/3)"}
    
    return {"success": result.get("success", False), "message": result.get("message", "")}

@app.get("/api/psych")
async def api_psych():
    """获取心理状态"""
    if not hasattr(app.state, 'psych_tracker') or app.state.psych_tracker is None:
        return {"error": "Psych tracker not loaded"}
    latest = app.state.psych_tracker.get_latest()
    return {"state": latest}

@app.get("/api/reset/logs")
async def api_reset_logs(limit: int = 10):
    """获取重置日志"""
    if not hasattr(app.state, 'reset_manager') or app.state.reset_manager is None:
        return {"error": "Reset manager not loaded"}
    logs = app.state.reset_manager.get_logs(limit=limit)
    return {"logs": logs}


def get_init_html() -> str:
    return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>ALLSPARK — INIT</title>
<style>
:root {
  --bg: #0a0a0a; --card: #141414; --border: #2a2a2a;
  --text: #e0e0e0; --text-dim: #888;
  --accent: #ff6b35; --accent-dim: #cc5529;
  --success: #44cc44; --danger: #ff4444; --warning: #ffaa00;
}
* { margin:0; padding:0; box-sizing:border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--bg); color: var(--text);
  min-height: 100vh; display: flex; align-items: center; justify-content: center;
}
.init-container {
  max-width: 560px; width: 100%; padding: 20px;
}
.init-card {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 8px; padding: 32px 24px; margin-bottom: 16px;
}
.init-card h1 { font-size: 1.5rem; color: var(--accent); margin-bottom: 4px; }
.init-card .subtitle { color: var(--text-dim); font-size: 0.85rem; margin-bottom: 24px; }
.step-indicator {
  display: flex; gap: 8px; margin-bottom: 24px;
}
.step-dot {
  flex: 1; height: 4px; border-radius: 2px; background: var(--border);
  transition: background 0.3s;
}
.step-dot.active { background: var(--accent); }
.step-dot.done { background: var(--success); }

.step { display: none; }
.step.active { display: block; }

h2 { font-size: 1.1rem; color: var(--accent); margin-bottom: 16px; }

.hw-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 16px;
}
.hw-item {
  background: var(--bg); border: 1px solid var(--border); border-radius: 8px;
  padding: 10px; text-align: center;
}
.hw-item .label { font-size: 0.7rem; color: var(--text-dim); margin-bottom: 2px; }
.hw-item .value { font-size: 0.95rem; font-weight: 600; }

.tier-badge {
  display: inline-block; padding: 6px 16px; border-radius: 8px;
  font-weight: 700; font-size: 0.9rem; margin-bottom: 12px;
}
.tier-phantom { background: #ff444433; color: #ff6666; }
.tier-minimum { background: #ffaa0033; color: #ffcc44; }
.tier-recommended { background: #44cc4433; color: #66ee66; }
.tier-comfortable { background: #4488ff33; color: #66aaff; }
.tier-flagship { background: #aa44ff33; color: #cc66ff; }

.model-card {
  background: var(--bg); border: 1px solid var(--border); border-radius: 8px;
  padding: 14px; margin-bottom: 10px;
}
.model-card.recommended { border-color: var(--accent); }
.model-card .model-name { font-weight: 600; font-size: 0.95rem; }
.model-card .model-info { font-size: 0.8rem; color: var(--text-dim); margin-top: 4px; }
.model-card .model-status { margin-top: 8px; font-size: 0.8rem; }

.btn {
  display: inline-block; padding: 10px 24px; border: none; border-radius: 8px;
  font-size: 0.9rem; cursor: pointer; transition: all 0.2s;
}
.btn-primary { background: var(--accent); color: #fff; }
.btn-primary:hover { background: var(--accent-dim); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-secondary { background: var(--card); color: var(--text); border: 1px solid var(--border); }
.btn-secondary:hover { border-color: var(--accent); }

.btn-row { display: flex; gap: 10px; margin-top: 20px; justify-content: flex-end; }

.input-field {
  width: 100%; padding: 10px 14px; border: 1px solid var(--border);
  border-radius: 8px; background: var(--bg); color: var(--text);
  font-size: 0.9rem; outline: none; margin-bottom: 12px;
}
.input-field:focus { border-color: var(--accent); }

.lang-option {
  display: flex; gap: 12px; margin-bottom: 16px;
}
.lang-btn {
  flex: 1; padding: 16px; border: 2px solid var(--border); border-radius: 8px;
  background: var(--bg); color: var(--text); cursor: pointer; text-align: center;
  transition: all 0.2s;
}
.lang-btn:hover { border-color: var(--accent); }
.lang-btn.selected { border-color: var(--accent); background: #ff6b3515; }
.lang-btn .lang-name { font-size: 1.1rem; font-weight: 600; }
.lang-btn .lang-desc { font-size: 0.75rem; color: var(--text-dim); margin-top: 4px; }

.progress-bar { height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; margin-top: 8px; }
.progress-fill { height: 100%; background: var(--accent); border-radius: 3px; transition: width 0.5s; }

.skip-link { color: var(--text-dim); font-size: 0.8rem; cursor: pointer; margin-top: 12px; display: inline-block; }
.skip-link:hover { color: var(--text); }

@media (max-width: 480px) {
  .init-container { padding: 12px; }
  .init-card { padding: 20px 16px; }
  .hw-grid { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<div class="init-container">
  <div class="init-card">
    <h1>ALLSPARK</h1>
    <div class="subtitle">Offline AI Survival System</div>

    <div class="step-indicator">
      <div class="step-dot" id="dot-1"></div>
      <div class="step-dot" id="dot-2"></div>
      <div class="step-dot" id="dot-3"></div>
      <div class="step-dot" id="dot-4"></div>
    </div>

    <div class="step" id="step-1">
      <h2>⚡ Step 1: Hardware Detection</h2>
      <div id="hw-loading" style="text-align:center;padding:20px;color:var(--text-dim);">Detecting hardware...</div>
      <div id="hw-info" style="display:none">
        <div id="hw-tier-badge" class="tier-badge"></div>
        <div class="hw-grid" id="hw-grid"></div>
      </div>
      <div class="btn-row">
        <button class="btn btn-primary" onclick="goStep(2)" id="btn-step1-next" disabled>Next →</button>
      </div>
    </div>

    <div class="step" id="step-2">
      <h2>🌐 Step 2: Language</h2>
      <div class="lang-option">
        <div class="lang-btn" onclick="selectLang('zh', this)" id="lang-zh">
          <div class="lang-name">中文</div>
          <div class="lang-desc">Chinese</div>
        </div>
        <div class="lang-btn" onclick="selectLang('en', this)" id="lang-en">
          <div class="lang-name">English</div>
          <div class="lang-desc">英文</div>
        </div>
      </div>
      <div class="btn-row">
        <button class="btn btn-secondary" onclick="goStep(1)">← Back</button>
        <button class="btn btn-primary" onclick="goStep(3)" id="btn-step2-next" disabled>Next →</button>
      </div>
    </div>

    <div class="step" id="step-3">
      <h2>🤖 Step 3: AI Model Setup</h2>
      <div id="model-info"></div>
      <div id="model-actions"></div>
      <div class="btn-row">
        <button class="btn btn-secondary" onclick="goStep(2)">← Back</button>
        <button class="btn btn-primary" onclick="goStep(4)">Next →</button>
      </div>
      <span class="skip-link" onclick="goStep(4)">Skip model setup →</span>
    </div>

    <div class="step" id="step-4">
      <h2>👤 Step 4: Survivor Profile</h2>
      <input class="input-field" id="survivor-name" type="text" placeholder="Your name / 你的名字" value="Survivor">
      <div class="btn-row">
        <button class="btn btn-secondary" onclick="goStep(3)">← Back</button>
        <button class="btn btn-primary" onclick="completeInit()" id="btn-complete">🔥 Initialize AllSpark</button>
      </div>
    </div>
  </div>
</div>

<script>
let currentStep = 0;
let selectedLang = "";
let hwData = null;

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  return res.json();
}

function goStep(n) {
  currentStep = n;
  document.querySelectorAll(".step").forEach(el => el.classList.remove("active"));
  document.getElementById("step-" + n).classList.add("active");
  document.querySelectorAll(".step-dot").forEach((dot, i) => {
    dot.classList.remove("active", "done");
    if (i + 1 < n) dot.classList.add("done");
    if (i + 1 === n) dot.classList.add("active");
  });
  if (n === 1) loadHardware();
  if (n === 3) loadModels();
}

async function loadHardware() {
  const data = await api("/api/init/hardware");
  hwData = data;
  document.getElementById("hw-loading").style.display = "none";
  document.getElementById("hw-info").style.display = "block";

  const tierMap = {
    phantom: ["Phantom (2GB)", "tier-phantom"],
    minimum: ["Minimum (4GB)", "tier-minimum"],
    recommended: ["Recommended (8GB)", "tier-recommended"],
    comfortable: ["Comfortable (16GB)", "tier-comfortable"],
    flagship: ["Flagship (32GB+)", "tier-flagship"],
  };
  const [tierName, tierClass] = tierMap[data.tier] || ["Unknown", "tier-minimum"];
  const badge = document.getElementById("hw-tier-badge");
  badge.textContent = tierName;
  badge.className = "tier-badge " + tierClass;

  document.getElementById("hw-grid").innerHTML = [
    ["CPU", data.cpu_model || data.cpu_arch],
    ["Cores", data.cpu_cores],
    ["RAM", data.ram_total_gb + " GB"],
    ["Storage", data.storage_available_gb + " / " + data.storage_total_gb + " GB"],
    ["GPU", data.gpu_info || "None"],
    ["OS", data.os_name],
  ].map(([l, v]) => `<div class="hw-item"><div class="label">${l}</div><div class="value">${v}</div></div>`).join("");

  document.getElementById("btn-step1-next").disabled = false;
}

function selectLang(lang, el) {
  selectedLang = lang;
  document.querySelectorAll(".lang-btn").forEach(b => b.classList.remove("selected"));
  el.classList.add("selected");
  document.getElementById("btn-step2-next").disabled = false;
}

async function loadModels() {
  const container = document.getElementById("model-info");
  const actions = document.getElementById("model-actions");
  if (!hwData) return;

  const model = hwData.recommended_model;
  const size = hwData.model_size_gb;
  const speed = hwData.model_speed_tps;
  const downloaded = hwData.model_downloaded;

  let html = `<div class="model-card recommended">
    <div class="model-name">⭐ ${model} (Recommended)</div>
    <div class="model-info">Size: ~${size}GB | Est. speed: ${speed} tokens/s</div>`;

  if (downloaded) {
    html += `<div class="model-status" style="color:var(--success)">✅ Model file found</div>`;
  } else {
    html += `<div class="model-status" style="color:var(--warning)">⬇️ Not downloaded yet</div>`;
  }
  html += `</div>`;

  if (!downloaded && hwData.llm_enabled) {
    html += `<div style="margin-top:12px;">
      <button class="btn btn-primary" onclick="downloadModel('${model}')" id="btn-download">
        ⬇️ Download ${model} (~${size}GB)
      </button>
      <div id="download-progress" style="display:none;margin-top:8px;">
        <div class="progress-bar"><div class="progress-fill" id="dl-fill" style="width:0%"></div></div>
        <div style="font-size:0.75rem;color:var(--text-dim);margin-top:4px;" id="dl-status">Starting...</div>
      </div>
    </div>`;
  } else if (!hwData.llm_enabled) {
    html += `<div style="margin-top:8px;font-size:0.8rem;color:var(--text-dim);">
      ⚠️ Hardware does not support LLM. Rule engine will be used for survival advice.
    </div>`;
  }

  container.innerHTML = html;
  actions.innerHTML = "";
}

async function downloadModel(modelName) {
  const btn = document.getElementById("btn-download");
  btn.disabled = true;
  btn.textContent = "Downloading...";
  document.getElementById("download-progress").style.display = "block";

  await api("/api/init/download?model_name=" + encodeURIComponent(modelName), {method: "POST"});

  const sizeBytes = (hwData.model_size_gb || 2) * 1024 * 1024 * 1024;
  const checkInterval = setInterval(async () => {
    const prog = await api("/api/init/download_progress?model_name=" + encodeURIComponent(modelName));
    if (prog.status === "done") {
      clearInterval(checkInterval);
      document.getElementById("dl-fill").style.width = "100%";
      document.getElementById("dl-status").textContent = "✅ Download complete!";
      btn.textContent = "✅ Model Ready";
      hwData.model_downloaded = true;
    } else if (prog.status === "downloading") {
      const pct = Math.min(95, (prog.current_bytes / sizeBytes) * 100);
      document.getElementById("dl-fill").style.width = pct + "%";
      const mb = (prog.current_bytes / (1024*1024)).toFixed(0);
      document.getElementById("dl-status").textContent = `Downloaded: ${mb} MB`;
    }
  }, 2000);
}

async function completeInit() {
  const btn = document.getElementById("btn-complete");
  btn.disabled = true;
  btn.textContent = "Initializing...";

  const name = document.getElementById("survivor-name").value.trim() || "Survivor";
  const lang = selectedLang || "zh";

  try {
    await api(`/api/init/complete?language=${lang}&survivor_name=${encodeURIComponent(name)}`, {method: "POST"});
    window.location.reload();
  } catch(e) {
    btn.textContent = "Error: " + e.message;
    btn.disabled = false;
  }
}

goStep(1);
</script>
</body>
</html>'''


def get_index_html() -> str:
    return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>ALLSPARK</title>
<style>
:root {
  --bg: #0a0a0a;
  --card: #141414;
  --card-hover: #1a1a1a;
  --border: #2a2a2a;
  --text: #e0e0e0;
  --text-dim: #666;
  --accent: #ff6b35;
  --accent-dim: #cc5529;
  --danger: #ff4444;
  --warning: #ffaa00;
  --success: #44cc44;
  --info: #4488ff;
  --mono: "JetBrains Mono", "Fira Code", "SF Mono", "Cascadia Code", monospace;
}
* { margin:0; padding:0; box-sizing:border-box; }
body {
  font-family: var(--mono), -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  overflow-x: hidden;
}
.app { max-width: 1200px; margin: 0 auto; padding: 12px; }

header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 12px;
}
header h1 { font-size: 1.2rem; color: var(--accent); }
header .phase-badge {
  padding: 4px 12px;
  border-radius: 8px;
  font-size: 0.8rem;
  font-weight: 600;
}
.phase-0 { background: #ff444433; color: #ff6666; }
.phase-1 { background: #ffaa0033; color: #ffcc44; }
.phase-2 { background: #44cc4433; color: #66ee66; }
.phase-3 { background: #4488ff33; color: #66aaff; }
.phase-4 { background: #aa44ff33; color: #cc66ff; }

nav {
  display: flex;
  gap: 6px;
  margin-bottom: 12px;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}
nav::-webkit-scrollbar { display: none; }
nav button {
  flex-shrink: 0;
  padding: 8px 16px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--card);
  color: var(--text-dim);
  font-size: 0.85rem;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}
nav button:hover { background: var(--card-hover); color: var(--text); }
nav button.active {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}

.tab-content { display: none; }
.tab-content.active { display: block; }

.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 12px;
}
.card h2 {
  font-size: 1rem;
  margin-bottom: 12px;
  color: var(--accent);
  display: flex;
  align-items: center;
  gap: 8px;
}

.resource-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 10px;
}
.resource-item {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  text-align: center;
}
.resource-item .icon { font-size: 1.5rem; margin-bottom: 4px; }
.resource-item .name { font-size: 0.8rem; color: var(--text-dim); margin-bottom: 4px; }
.resource-item .value { font-size: 1.3rem; font-weight: 700; }
.resource-item .remaining { font-size: 0.75rem; color: var(--text-dim); margin-top: 4px; }
.resource-bar {
  height: 4px;
  background: var(--border);
  border-radius: 2px;
  margin-top: 8px;
  overflow: hidden;
}
.resource-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.5s;
}

.warning-list { list-style: none; }
.warning-item {
  padding: 8px 12px;
  border-radius: 6px;
  margin-bottom: 6px;
  font-size: 0.85rem;
}
.warning-critical { background: #ff444422; border-left: 3px solid var(--danger); color: #ff6666; }
.warning-warning { background: #ffaa0022; border-left: 3px solid var(--warning); color: #ffcc44; }

.search-box {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.search-box input {
  flex: 1;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg);
  color: var(--text);
  font-size: 0.9rem;
  outline: none;
}
.search-box input:focus { border-color: var(--accent); }
.search-box button {
  padding: 10px 20px;
  border: none;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  font-size: 0.9rem;
  cursor: pointer;
}
.search-box button:hover { background: var(--accent-dim); }

.knowledge-entry {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px;
  margin-bottom: 10px;
  cursor: pointer;
  transition: border-color 0.2s;
}
.knowledge-entry:hover { border-color: var(--accent); }
.knowledge-entry .title { font-weight: 600; margin-bottom: 6px; }
.knowledge-entry .meta { font-size: 0.75rem; color: var(--text-dim); margin-bottom: 6px; }
.knowledge-entry .summary { font-size: 0.85rem; color: var(--text-dim); }

.knowledge-detail {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
}
.knowledge-detail h3 { color: var(--accent); margin-bottom: 12px; }
.knowledge-detail .section { margin-bottom: 12px; }
.knowledge-detail .section-title { font-size: 0.8rem; color: var(--text-dim); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px; }
.knowledge-detail ol { padding-left: 20px; }
.knowledge-detail li { font-size: 0.85rem; margin-bottom: 4px; }
.knowledge-detail .warning-text { color: var(--warning); font-size: 0.85rem; }

.chat-container { display: flex; flex-direction: column; height: calc(100vh - 200px); min-height: 300px; }
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 10px;
}
.chat-msg { margin-bottom: 12px; }
.chat-msg.user { text-align: right; }
.chat-msg .bubble {
  display: inline-block;
  max-width: 80%;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 0.85rem;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}
.chat-msg.user .bubble { background: var(--accent); color: #fff; border-bottom-right-radius: 4px; }
.chat-msg.system .bubble { background: var(--card); border: 1px solid var(--border); border-bottom-left-radius: 4px; }
.chat-input {
  display: flex;
  gap: 8px;
}
.chat-input input {
  flex: 1;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg);
  color: var(--text);
  font-size: 0.9rem;
  outline: none;
}
.chat-input input:focus { border-color: var(--accent); }
.chat-input button {
  padding: 12px 20px;
  border: none;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  cursor: pointer;
  font-size: 0.9rem;
}

.exp-item {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.exp-item .info { flex: 1; }
.exp-item .event { font-weight: 600; font-size: 0.9rem; }
.exp-item .outcome { font-size: 0.8rem; color: var(--text-dim); margin-top: 2px; }
.exp-item .badge {
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 0.7rem;
  font-weight: 600;
}
.badge-promoted { background: #44cc4433; color: var(--success); }
.badge-raw { background: var(--border); color: var(--text-dim); }

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}
.stat-item {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  text-align: center;
}
.stat-item .stat-value { font-size: 1.5rem; font-weight: 700; color: var(--accent); }
.stat-item .stat-label { font-size: 0.75rem; color: var(--text-dim); margin-top: 4px; }

.module-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
}
.module-item:last-child { border-bottom: none; }
.module-item .name { font-size: 0.85rem; }
.module-item .desc { font-size: 0.75rem; color: var(--text-dim); }
.module-status {
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 0.7rem;
  font-weight: 600;
}
.status-loaded { background: #44cc4433; color: var(--success); }
.status-disabled { background: #ff444433; color: var(--danger); }
.status-available { background: #4488ff33; color: var(--info); }

.back-btn {
  display: inline-block;
  padding: 6px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--card);
  color: var(--text-dim);
  font-size: 0.8rem;
  cursor: pointer;
  margin-bottom: 10px;
}
.back-btn:hover { color: var(--text); border-color: var(--accent); }

@media (max-width: 600px) {
  .app { padding: 8px; }
  header { padding: 10px 12px; }
  header h1 { font-size: 1rem; }
  .resource-grid { grid-template-columns: repeat(2, 1fr); gap: 8px; }
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
  nav button { padding: 6px 12px; font-size: 0.8rem; }
  .chat-container { height: calc(100vh - 180px); }
}
@media (max-width: 380px) {
  .resource-grid { grid-template-columns: 1fr; }
  .stats-grid { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<div class="app">
  <header>
    <h1>ALLSPARK</h1>
    <span id="phase-badge" class="phase-badge phase-0">PHASE 0</span>
  </header>

  <nav id="nav">
    <button class="active" data-tab="dashboard">📊 Dashboard</button>
    <button data-tab="knowledge">📚 Knowledge</button>
    <button data-tab="chat">💬 Chat</button>
    <button data-tab="experience">🧠 Experience</button>
    <button data-tab="modules">🔧 Modules</button>
  </nav>

  <div id="tab-dashboard" class="tab-content active">
    <div class="card">
      <h2>⚡ Resources</h2>
      <div id="resource-grid" class="resource-grid"></div>
    </div>
    <div class="card">
      <h2>⚠️ Warnings</h2>
      <ul id="warning-list" class="warning-list"></ul>
    </div>
    <div class="card">
      <h2>📋 Active Tasks</h2>
      <div id="task-list"></div>
    </div>
  </div>

  <div id="tab-knowledge" class="tab-content">
    <div class="search-box">
      <input id="knowledge-search" type="text" placeholder="Search knowledge..." autocomplete="off">
      <button onclick="searchKnowledge()">Search</button>
    </div>
    <div id="knowledge-results"></div>
    <div id="knowledge-detail" style="display:none"></div>
  </div>

  <div id="tab-chat" class="tab-content">
    <div class="chat-container">
      <div id="chat-messages" class="chat-messages"></div>
      <div class="chat-input">
        <input id="chat-input" type="text" placeholder="Ask AllSpark..." autocomplete="off">
        <button onclick="sendChat()">Send</button>
      </div>
    </div>
  </div>

  <div id="tab-experience" class="tab-content">
    <div class="card">
      <h2>📊 Stats</h2>
      <div id="exp-stats" class="stats-grid"></div>
    </div>
    <div class="card">
      <h2>📝 Log Experience</h2>
      <div style="display:flex;flex-direction:column;gap:8px;">
        <input id="exp-event" type="text" placeholder="Event (e.g. found water source)">
        <input id="exp-outcome" type="text" placeholder="Outcome (e.g. clean spring, 2L/hour)">
        <input id="exp-lesson" type="text" placeholder="Lesson (optional)">
        <button onclick="logExperience()" style="padding:10px;border:none;border-radius:8px;background:var(--accent);color:#fff;cursor:pointer;">Log</button>
      </div>
    </div>
    <div class="card">
      <h2>🔄 Recent</h2>
      <div id="exp-list"></div>
    </div>
  </div>

  <div id="tab-modules" class="tab-content">
    <div class="card">
      <h2>🔧 Module Status</h2>
      <div id="module-list"></div>
    </div>
    <div class="card">
      <h2>🤖 LLM</h2>
      <div id="llm-status"></div>
      <button onclick="loadLLM()" style="margin-top:8px;padding:8px 16px;border:none;border-radius:8px;background:var(--accent);color:#fff;cursor:pointer;">Load Model</button>
    </div>
  </div>
</div>

<script>
const API = "";
let currentTab = "dashboard";
let refreshInterval;

const resourceIcons = {
  water: "💧", food: "🍞", fire: "🔥", shelter: "🏠",
  medical: "💊", power: "⚡", communication: "📡"
};

function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll(".tab-content").forEach(el => el.classList.remove("active"));
  document.getElementById("tab-" + tab).classList.add("active");
  document.querySelectorAll("nav button").forEach(btn => btn.classList.remove("active"));
  document.querySelector(`nav button[data-tab="${tab}"]`).classList.add("active");
  if (tab === "dashboard") refreshDashboard();
  if (tab === "experience") refreshExperience();
  if (tab === "modules") refreshModules();
}

document.querySelectorAll("nav button").forEach(btn => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

async function api(path, opts = {}) {
  const res = await fetch(API + path, opts);
  return res.json();
}

async function refreshDashboard() {
  const data = await api("/api/status");
  const badge = document.getElementById("phase-badge");
  badge.textContent = "PHASE " + data.phase;
  badge.className = "phase-badge phase-" + data.phase;

  const grid = document.getElementById("resource-grid");
  const resourceLabels = {power:"⚡",water:"💧",food:"🍞",fire:"🔥",storage:"💾"};
  grid.innerHTML = data.resources.map(r => {
    if (r.offline) {
      return `<div class="resource-item" style="opacity:0.5">
        <div class="icon">${resourceLabels[r.type] || "📦"}</div>
        <div class="name">${r.type}</div>
        <div class="value" style="color:var(--text-dim)">--</div>
        <div class="remaining">OFFLINE</div>
        <div class="resource-bar"><div class="resource-bar-fill" style="width:0%;background:var(--border)"></div></div>
      </div>`;
    }
    const pct = Math.min(100, Math.max(0, (r.remaining_hours / 168) * 100));
    const color = pct > 50 ? "var(--success)" : pct > 20 ? "var(--warning)" : "var(--danger)";
    return `<div class="resource-item">
      <div class="icon">${resourceLabels[r.type] || "📦"}</div>
      <div class="name">${r.type}</div>
      <div class="value" style="font-family:'JetBrains Mono','Fira Code','SF Mono',monospace">${r.amount}<span style="font-size:0.7em;color:var(--text-dim)">${r.unit}</span></div>
      <div class="remaining">~${Math.round(r.remaining_hours)}h left</div>
      <div class="resource-bar"><div class="resource-bar-fill" style="width:${pct}%;background:${color}"></div></div>
    </div>`;
  }).join("");

  const wlist = document.getElementById("warning-list");
  if (data.warnings && data.warnings.length) {
    wlist.innerHTML = data.warnings.map(w =>
      `<li class="warning-item warning-${w.level}">${w.level === "critical" ? "🚨" : "⚠️"} ${w.message}</li>`
    ).join("");
  } else {
    wlist.innerHTML = '<li style="color:var(--text-dim);font-size:0.85rem;">No warnings</li>';
  }

  const tasks = await api("/api/tasks");
  const tlist = document.getElementById("task-list");
  if (tasks.length) {
    tlist.innerHTML = tasks.slice(0, 5).map(t =>
      `<div style="padding:6px 0;border-bottom:1px solid var(--border);font-size:0.85rem;">
        <strong>P${t.phase}</strong> ${t.title}
      </div>`
    ).join("");
  } else {
    tlist.innerHTML = '<div style="color:var(--text-dim);font-size:0.85rem;">No active tasks</div>';
  }
}

async function searchKnowledge() {
  const q = document.getElementById("knowledge-search").value.trim();
  if (!q) return;
  const results = await api(`/api/knowledge/search?q=${encodeURIComponent(q)}`);
  const container = document.getElementById("knowledge-results");
  document.getElementById("knowledge-detail").style.display = "none";
  container.style.display = "block";
  if (!results.length) {
    container.innerHTML = '<div style="color:var(--text-dim);padding:20px;text-align:center;">No results found</div>';
    return;
  }
  container.innerHTML = results.map(e =>
    `<div class="knowledge-entry" onclick="showKnowledge('${e.id}')">
      <div class="title">${e.title}</div>
      <div class="meta">Tier ${e.priority} · ${e.category}/${e.subcategory}</div>
      <div class="summary">${e.summary.substring(0, 120)}...</div>
    </div>`
  ).join("");
}

async function showKnowledge(id) {
  const entry = await api(`/api/knowledge/${id}`);
  const container = document.getElementById("knowledge-detail");
  document.getElementById("knowledge-results").style.display = "none";
  container.style.display = "block";
  container.innerHTML = `
    <button class="back-btn" onclick="backToResults()">← Back</button>
    <div class="knowledge-detail">
      <h3>${entry.title}</h3>
      <div class="section">
        <div class="section-title">Summary</div>
        <p style="font-size:0.85rem;">${entry.summary}</p>
      </div>
      ${entry.steps && entry.steps.length ? `<div class="section">
        <div class="section-title">Steps</div>
        <ol>${entry.steps.map(s => `<li>${s}</li>`).join("")}</ol>
      </div>` : ""}
      ${entry.warnings && entry.warnings.length ? `<div class="section">
        <div class="section-title">⚠️ Warnings</div>
        ${entry.warnings.map(w => `<div class="warning-text">• ${w}</div>`).join("")}
      </div>` : ""}
      <div style="font-size:0.75rem;color:var(--text-dim);margin-top:8px;">
        Tier ${entry.priority} · ${entry.category}/${entry.subcategory} · ${entry.verification} · ${entry.source}
      </div>
    </div>`;
}

function backToResults() {
  document.getElementById("knowledge-detail").style.display = "none";
  document.getElementById("knowledge-results").style.display = "block";
}

document.getElementById("knowledge-search").addEventListener("keydown", e => {
  if (e.key === "Enter") searchKnowledge();
});

async function sendChat() {
  const input = document.getElementById("chat-input");
  const msg = input.value.trim();
  if (!msg) return;
  input.value = "";
  addChatMsg("user", msg);
  addChatMsg("system", "...");
  try {
    const data = await api("/api/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({message: msg})
    });
    document.querySelector(".chat-msg.system:last-child .bubble").textContent = data.response;
  } catch(e) {
    document.querySelector(".chat-msg.system:last-child .bubble").textContent = "Error: " + e.message;
  }
  scrollChat();
}

function addChatMsg(role, text) {
  const container = document.getElementById("chat-messages");
  container.innerHTML += `<div class="chat-msg ${role}"><div class="bubble">${escHtml(text)}</div></div>`;
  scrollChat();
}

function scrollChat() {
  const c = document.getElementById("chat-messages");
  c.scrollTop = c.scrollHeight;
}

function escHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

document.getElementById("chat-input").addEventListener("keydown", e => {
  if (e.key === "Enter") sendChat();
});

async function refreshExperience() {
  const data = await api("/api/experience");
  const list = document.getElementById("exp-list");
  if (!data.length) {
    list.innerHTML = '<div style="color:var(--text-dim);font-size:0.85rem;">No experiences yet</div>';
    return;
  }
  list.innerHTML = data.map(e =>
    `<div class="exp-item">
      <div class="info">
        <div class="event">${escHtml(e.event)}</div>
        <div class="outcome">${escHtml(e.outcome)}</div>
      </div>
      <span class="badge ${e.promoted ? 'badge-promoted' : 'badge-raw'}">${e.promoted ? "Promoted" : "Raw"}</span>
    </div>`
  ).join("");

  const stats = await api("/api/status");
  const sgrid = document.getElementById("exp-stats");
  if (stats.experience) {
    sgrid.innerHTML = `
      <div class="stat-item"><div class="stat-value">${stats.experience.total_experiences}</div><div class="stat-label">Experiences</div></div>
      <div class="stat-item"><div class="stat-value">${stats.experience.patterns_detected}</div><div class="stat-label">Patterns</div></div>
      <div class="stat-item"><div class="stat-value">${stats.experience.knowledge_promoted}</div><div class="stat-label">Promoted</div></div>`;
  }
}

async function logExperience() {
  const event = document.getElementById("exp-event").value.trim();
  const outcome = document.getElementById("exp-outcome").value.trim();
  const lesson = document.getElementById("exp-lesson").value.trim();
  if (!event || !outcome) return;
  await api("/api/experience", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({event, outcome, lesson})
  });
  document.getElementById("exp-event").value = "";
  document.getElementById("exp-outcome").value = "";
  document.getElementById("exp-lesson").value = "";
  refreshExperience();
}

async function refreshModules() {
  const status = await api("/api/status");
  const list = document.getElementById("module-list");
  if (status.modules && status.modules.length) {
    list.innerHTML = status.modules.map(m =>
      `<div class="module-item">
        <div><div class="name">${m.name}${m.is_core ? " ⭐" : ""}</div><div class="desc">${m.description_en}</div></div>
        <span class="module-status status-${m.status}">${m.status}</span>
      </div>`
    ).join("");
  }

  const llm = await api("/api/llm/status");
  const ldiv = document.getElementById("llm-status");
  ldiv.innerHTML = `
    <div style="font-size:0.85rem;">Model: <strong>${llm.model_name}</strong></div>
    <div style="font-size:0.85rem;">Available: ${llm.available ? "✅" : "❌"}</div>
    ${llm.error ? `<div style="font-size:0.8rem;color:var(--danger);margin-top:4px;">${llm.error}</div>` : ""}`;
}

async function loadLLM() {
  const res = await api("/api/llm/load", {method: "POST"});
  refreshModules();
}

refreshDashboard();
refreshInterval = setInterval(() => {
  if (currentTab === "dashboard") refreshDashboard();
}, 30000);
</script>
</body>
</html>'''
