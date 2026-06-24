import urllib.request
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader

from allspark import __version__
from allspark.adapters.routes.helpers import http_exception_handler
from allspark.bootstrap import ApplicationBootstrap
from allspark.core.config import DEFAULT_DB_DIR
from allspark.core.database import Database
from allspark.core.i18n import MESSAGES, get_language, init_language, set_language, t
from allspark.infrastructure.hardware import compute_feature_flags, detect_hardware
from allspark.infrastructure.module_loader import ModuleRegistry

MODELS_DIR = DEFAULT_DB_DIR / "models"

# Model URLs and metadata live in allspark/data/models.yaml.
# Use model_registry to access them.
from allspark.services import model_registry as _registry  # noqa: E402

# Jinja2 template environment
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)


def _render_template(name: str, **context) -> str:
    template = _jinja_env.get_template(name)
    context.setdefault("t", t)
    lang = get_language()
    context.setdefault("lang", lang)
    context.setdefault("version", __version__)
    # Inject all web_ prefixed i18n keys as window.I18N for JS-side usage
    web_i18n = {
        k: v for k, v in MESSAGES.get(lang, {}).items()
        if k.startswith("web_")
        or k.startswith("error_")
        or k.startswith("psych_")
        or k.startswith("mode_")
        or k.startswith("resource_")
        or k.startswith("q_")
    }
    context.setdefault("web_i18n", web_i18n)
    return template.render(**context)


MODEL_DOWNLOAD_URLS = {
    entry.name: entry.url_hf for entry in _registry.list_models() if entry.url_hf
}
MIRROR_DOWNLOAD_URLS = {
    entry.name: entry.url_mirror for entry in _registry.list_models() if entry.url_mirror
}


def create_app(db_path: Optional[str] = None) -> FastAPI:
    app = FastAPI(title="ALLSPARK", version=__version__)
    app.add_exception_handler(HTTPException, http_exception_handler)

    db = Database(Path(db_path) if db_path else None)
    init_language(db)
    app.state.db = db
    app.state.engine = None
    app.state.initialized = db.is_initialized()

    if app.state.initialized:
        _load_engine(app)

    # HTML pages
    @app.get("/", response_class=HTMLResponse)
    async def index():
        if not app.state.initialized:
            return _render_template("init.html")
        # SHA-60: page_title flows into the topbar and <title>; route it
        # through t() so it is not a hardcoded English leak in zh mode.
        return _render_template("index.html", page_title=t("web_page_title_dashboard"))

    @app.get("/system", response_class=HTMLResponse)
    async def system_page():
        if not app.state.initialized:
            return _render_template("init.html")
        return _render_template("system.html", page_title=t("web_page_title_system"))

    @app.get("/executions", response_class=HTMLResponse)
    async def executions_page():
        if not app.state.initialized:
            return _render_template("init.html")
        return _render_template("executions.html", page_title=t("web_page_title_executions"))

    @app.get("/config", response_class=HTMLResponse)
    async def config_page():
        if not app.state.initialized:
            return _render_template("init.html")
        return _render_template("config.html", page_title=t("web_page_title_config"))

    @app.get("/repository", response_class=HTMLResponse)
    async def repository_page():
        if not app.state.initialized:
            return _render_template("init.html")
        return _render_template("repository.html", page_title=t("web_page_title_repository"))

    # Init API routes
    _register_init_routes(app)

    # API routes (from sub-modules)
    from allspark.adapters.routes.helpers import _require_init
    check = _require_init(app)

    from allspark.adapters.routes.core import register_core_routes
    register_core_routes(app, check)

    from allspark.adapters.routes.skf import register_skf_routes
    register_skf_routes(app, check)

    from allspark.adapters.routes.network import register_network_routes
    register_network_routes(app, check)

    from allspark.adapters.routes.governance import register_governance_routes
    register_governance_routes(app, check)

    from allspark.adapters.routes.hardware import register_hardware_routes
    register_hardware_routes(app, check)

    from allspark.adapters.routes.survival import register_survival_routes
    register_survival_routes(app, check)

    from allspark.adapters.routes.system import register_system_routes
    register_system_routes(app, check)

    return app


def _load_engine(app):
    db = app.state.db

    registry_loaded = ModuleRegistry.load_from_db(db)
    if registry_loaded:
        flags = registry_loaded.flags
    else:
        profile = detect_hardware()
        flags = compute_feature_flags(profile.tier, profile.gpu_available)

    container = ApplicationBootstrap(db, flags=flags).bootstrap()
    engine = container.get("rule_engine")
    app.state.engine = engine
    app.state.container = container


def _register_init_routes(app):
    @app.get("/api/init/status")
    async def init_status():
        return {"initialized": app.state.initialized}

    @app.get("/api/init/questionnaire")
    async def init_questionnaire():
        """Structured questionnaire options (PRD §4.2.2).

        Single source of truth is ``allspark/data/questionnaire.yaml``, shared
        with the CLI wizard — the Web init wizard renders from this so the two
        paths cannot drift (SHA-56). Each option carries a stable ``key``
        (persisted in survivor_state) and a ``label_key`` resolved client-side
        via the q_* i18n keys.
        """
        from allspark.adapters.init_wizard import _load_questionnaire

        return {"version": "2", "questions": _load_questionnaire()}

    @app.get("/api/init/hardware")
    async def init_hardware():
        from allspark.infrastructure.hardware import LLM_MODEL_MAP
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
        mirror_url = MIRROR_DOWNLOAD_URLS.get(model_name)
        if not url:
            raise HTTPException(400, f"Unknown model: {model_name}")
        filename = url.split("/")[-1]
        dest = MODELS_DIR / filename
        MODELS_DIR.mkdir(parents=True, exist_ok=True)

        if dest.exists():
            return {"status": "already_exists", "path": str(dest)}

        tmp = dest.with_suffix(".tmp")
        if tmp.exists():
            return {"status": "downloading", "model": model_name, "path": str(dest)}

        try:
            import ssl
            import threading

            urls_to_try = [url]
            if mirror_url and mirror_url != url:
                urls_to_try.append(mirror_url)

            def _download():
                last_error = None
                for try_url in urls_to_try:
                    try:
                        ctx = ssl.create_default_context()
                        req = urllib.request.Request(try_url, headers={"User-Agent": "AllSpark/0.2.0"})
                        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                            with open(str(tmp), "wb") as f:
                                while True:
                                    chunk = resp.read(8192)
                                    if not chunk:
                                        break
                                    f.write(chunk)
                        tmp.rename(dest)
                        return  # Success
                    except Exception as e:
                        if tmp.exists():
                            tmp.unlink()
                        last_error = e
                        continue
                # All sources failed
                error_file = dest.with_suffix(".error")
                error_file.write_text(str(last_error) if last_error else "All download sources failed")

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
        error_file = dest.with_suffix(".error")

        if dest.exists():
            return {"status": "done", "path": str(dest)}
        if error_file.exists():
            error_msg = error_file.read_text()
            error_file.unlink()
            if tmp.exists():
                tmp.unlink()
            return {"status": "error", "message": error_msg}
        if tmp.exists():
            current_size = tmp.stat().st_size
            return {"status": "downloading", "current_bytes": current_size}
        return {"status": "not_started"}

    @app.post("/api/init/complete")
    async def init_complete(
        request: Request,
        language: str = Query("zh"),
        survivor_name: str = Query("Survivor"),
        skip_model: bool = Query(False),
        location_type: str = Query(""),
        shelter: str = Query(""),
        health: str = Query(""),
        urgency: str = Query(""),
        threats: str = Query(""),
        skills: str = Query(""),
    ):
        # The structured questionnaire fields may arrive either as query
        # params (legacy GET-style POST) or as a JSON body (Web wizard).
        # Merge JSON body on top so the Web init wizard can submit the full
        # PRD §4.2.2 questionnaire (SHA-56).
        body: dict = {}
        try:
            parsed = await request.json()
            if isinstance(parsed, dict):
                body = parsed
        except Exception:
            body = {}

        def _pick(key: str, default: str) -> str:
            val = body.get(key, default)
            if isinstance(val, list):
                return ",".join(str(v) for v in val if v)
            return str(val or default)

        location_type = _pick("location_type", location_type)
        shelter = _pick("shelter", shelter)
        health = _pick("health", health)
        urgency = _pick("urgency", urgency)
        threats = _pick("threats", threats)
        skills = _pick("skills", skills)
        survivor_name = _pick("survivor_name", survivor_name)
        language = _pick("language", language)

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
        # Persist the structured questionnaire so the survival assessment has
        # the same initial context the CLI wizard captures (SHA-56).
        db.save_survivor_state("location_type", location_type)
        db.save_survivor_state("shelter", shelter)
        db.save_survivor_state("health", health)
        db.save_survivor_state("urgency", urgency)
        db.save_survivor_state("threats", threats)
        db.save_survivor_state("skills", skills)
        db.save_survivor_state("questionnaire_version", "2")
        db.mark_initialized()

        app.state.initialized = True
        _load_engine(app)

        return {"status": "ok"}
