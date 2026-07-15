import hmac
import logging
import secrets
import threading
import urllib.request
from contextvars import ContextVar
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader

from allspark import __version__
from allspark.adapters.routes.helpers import http_exception_handler
from allspark.bootstrap import (
    PreparedApplication,
    cleanup_application_candidate,
    prepare_application,
    rollback_initialization_draft,
)
from allspark.core.config import DEFAULT_DB_DIR
from allspark.core.database import Database
from allspark.core.i18n import MESSAGES, get_language, init_language, set_language, t
from allspark.infrastructure.hardware import compute_feature_flags, detect_hardware
from allspark.infrastructure.module_loader import ModuleRegistry
from allspark.services.initial_assessment import (
    InitialAssessmentValidationError,
    assessment_preview,
    validate_initial_assessment,
)
from allspark.services.reset_manager import get_reset_descriptions

logger = logging.getLogger(__name__)

MODELS_DIR = DEFAULT_DB_DIR / "models"

# Model URLs and metadata live in allspark/data/models.yaml.
# Use model_registry to access them.
from allspark.services import model_registry as _registry  # noqa: E402

# Jinja2 template environment
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)


# Auth token gating HTML pages + /api/* when the Web UI binds non-loopback
# (audit H3 / SHA-142). Set by create_app(). The token is NEVER injected into
# HTML/DOM; the browser authenticates via an httpOnly cookie issued by
# /api/auth/login (or the init/complete bootstrap step). API clients may still
# use an Authorization: Bearer header.
_WEB_TOKEN: Optional[str] = None
_AUTH_COOKIE = "allspark_session"

# SHA-213: scripts use a per-request nonce and inline event handlers are
# forbidden. style-src remains a separate boundary because templates still use
# inline layout declarations and <style> blocks.
_CSP_NONCE: ContextVar[str] = ContextVar("allspark_csp_nonce", default="")
_CSP_NON_SCRIPT_DIRECTIVES = (
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'"
)


def build_csp_policy(nonce: str) -> str:
    return (
        f"default-src 'self'; script-src 'self' 'nonce-{nonce}'; "
        f"script-src-attr 'none'; {_CSP_NON_SCRIPT_DIRECTIVES}"
    )


def _is_authed(request: Request) -> bool:
    """True if the request carries the auth cookie or a valid Bearer header.

    Only called when ``_WEB_TOKEN`` is set (non-loopback); the middleware
    short-circuits loopback/no-token mode before reaching here.
    """
    token = _WEB_TOKEN
    if not token:
        return False
    cookie = request.cookies.get(_AUTH_COOKIE)
    if cookie and hmac.compare_digest(cookie, token):
        return True
    auth = request.headers.get("authorization", "")
    return auth == f"Bearer {token}"


def _set_auth_cookie(response, token: str):
    """Stamp the httpOnly session cookie on a response (SHA-142)."""
    response.set_cookie(
        _AUTH_COOKIE, token, httponly=True, samesite="strict", secure=False, path="/"
    )
    return response


def _render_template(name: str, **context) -> str:
    template = _jinja_env.get_template(name)
    context.setdefault("t", t)
    lang = get_language()
    context.setdefault("lang", lang)
    context.setdefault("version", __version__)
    context.setdefault("csp_nonce", _CSP_NONCE.get())
    # Inject all web_ prefixed i18n keys as window.I18N for JS-side usage
    web_i18n = {
        k: v for k, v in MESSAGES.get(lang, {}).items()
        if k.startswith("web_")
        or k.startswith("error_")
        or k.startswith("psych_")
        or k.startswith("mode_")
        or k.startswith("resource_")
        or k.startswith("knowledge_")
        or k.startswith("q_")
    }
    context.setdefault("web_i18n", web_i18n)
    init_prefixes = (
        "web_init_",
        "init_assessment_",
        "assessment_field_",
        "assessment_gap_",
        "error_assessment_",
        "resource_",
        "q_",
    )
    context.setdefault(
        "init_i18n",
        {
            language: {
                key: value
                for key, value in MESSAGES.get(language, {}).items()
                if key.startswith(init_prefixes)
            }
            for language in ("zh", "en")
        },
    )
    return template.render(**context)


MODEL_DOWNLOAD_URLS = {
    entry.name: entry.url_hf for entry in _registry.list_models() if entry.url_hf
}
MIRROR_DOWNLOAD_URLS = {
    entry.name: entry.url_mirror for entry in _registry.list_models() if entry.url_mirror
}


def create_app(db_path: Optional[str] = None, token: Optional[str] = None) -> FastAPI:
    global _WEB_TOKEN
    _WEB_TOKEN = token
    app = FastAPI(title="ALLSPARK", version=__version__)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.state.web_token = token

    # Auth gate (audit H3 / SHA-142). Loopback (no token) = local trust; only
    # the one-time bootstrap gate applies. Non-loopback (token set) = every HTML
    # page and /api/* endpoint requires the httpOnly auth cookie (set by
    # /api/auth/login or the init/complete bootstrap) or a Bearer header. The
    # token never enters HTML/DOM. /api/init/complete is one-time (410 once
    # initialized) so an attacker cannot re-init/overwrite the system.
    @app.middleware("http")
    async def enforce_auth(request: Request, call_next):
        path = request.url.path
        # One-time bootstrap: re-init forbidden once initialized.
        if path == "/api/init/complete" and app.state.initialized:
            return JSONResponse(
                status_code=410,
                content={
                    "status": "error",
                    "error": "bootstrap_closed",
                    "detail": "Instance already initialized; reset required to re-initialize",
                    "next_action": "",
                },
            )
        # Loopback / no-token mode: local trust.
        if not _WEB_TOKEN:
            return await call_next(request)
        # Public endpoints: login page + auth endpoints.
        if path in ("/login", "/api/auth/login", "/api/auth/logout"):
            return await call_next(request)
        # Everything else requires auth (cookie or Bearer).
        if not _is_authed(request):
            if path.startswith("/api/"):
                return JSONResponse(
                    status_code=401,
                    content={
                        "status": "error",
                        "error": "unauthorized",
                        "detail": "Authentication required",
                        "next_action": 'POST /api/auth/login with {"token": "<token>"}',
                    },
                )
            return RedirectResponse("/login", status_code=303)
        return await call_next(request)

    # SHA-213: enforce a per-request script nonce on every response. The nonce
    # is scoped through ContextVar so concurrent template renders cannot share
    # it; script-src-attr 'none' keeps inline event handlers blocked.
    @app.middleware("http")
    async def add_csp_header(request: Request, call_next):
        nonce = secrets.token_urlsafe(18)
        token = _CSP_NONCE.set(nonce)
        try:
            response = await call_next(request)
            response.headers["Content-Security-Policy"] = build_csp_policy(nonce)
            return response
        finally:
            _CSP_NONCE.reset(token)

    db = Database(Path(db_path) if db_path else None)
    init_language(db)
    app.state.db = db
    app.state.engine = None
    app.state.container = None
    app.state.initialized = db.is_initialized()
    app.state.init_lock = threading.Lock()

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
        return _render_template(
            "system.html",
            page_title=t("web_page_title_system"),
            reset_descriptions=get_reset_descriptions(),
        )

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

    @app.get("/login", response_class=HTMLResponse)
    async def login_page():
        # SHA-142: standalone login page (no base.html - pre-auth). The token
        # is never rendered here; the user pastes it and we exchange it for an
        # httpOnly cookie via /api/auth/login.
        return _render_template("login.html", page_title=t("web_login_title"))

    @app.post("/api/auth/login")
    async def auth_login(request: Request):
        token = _WEB_TOKEN
        body: dict = {}
        try:
            parsed = await request.json()
            if isinstance(parsed, dict):
                body = parsed
        except Exception:
            body = {}
        submitted = body.get("token") or ""
        if not isinstance(submitted, str) or not submitted:
            return JSONResponse(
                status_code=401,
                content={"status": "error", "error": "unauthorized", "detail": "token required"},
            )
        if not token or not hmac.compare_digest(submitted, token):
            return JSONResponse(
                status_code=401,
                content={"status": "error", "error": "unauthorized", "detail": "invalid token"},
            )
        return _set_auth_cookie(JSONResponse(content={"status": "ok"}), token)

    @app.post("/api/auth/logout")
    async def auth_logout():
        resp = JSONResponse(content={"status": "ok"})
        resp.delete_cookie(_AUTH_COOKIE, path="/")
        return resp

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


def _prepare_engine(app, flags=None) -> PreparedApplication:
    db = app.state.db
    if flags is None:
        registry_loaded = ModuleRegistry.load_from_db(db)
        if registry_loaded:
            flags = registry_loaded.flags
        else:
            profile = detect_hardware()
            flags = compute_feature_flags(profile.tier, profile.gpu_available)
    return prepare_application(db, flags=flags)


def _publish_engine(app, prepared: PreparedApplication) -> None:
    app.state.container = prepared.container
    app.state.engine = prepared.engine


def _load_engine(app) -> None:
    prepared = _prepare_engine(app)
    _publish_engine(app, prepared)


def _assessment_error_response(
    exc: InitialAssessmentValidationError, language: str | None = None
) -> JSONResponse:
    response_language = language if language in ("zh", "en") else get_language()

    def translate(key: str, **kwargs) -> str:
        template = MESSAGES.get(response_language, {}).get(key, key)
        try:
            return template.format(**kwargs)
        except (KeyError, ValueError):
            return template

    errors = []
    for error in exc.errors:
        field = error["field"]
        domain = field.split(".")[1] if field.startswith("resources.") else field
        label_key = (
            "assessment_field_confirmation"
            if domain == "confirmed"
            else f"assessment_field_{domain}"
        )
        code = error["code"]
        errors.append(
            {
                "field": field,
                "code": code,
                "message": translate(
                    f"error_assessment_{code}", field=translate(label_key)
                ),
            }
        )
    return JSONResponse(
        status_code=422,
        content={
            "status": "error",
            "error": "invalid_initial_assessment",
            "detail": translate("error_assessment_summary"),
            "errors": errors,
            "next_action": "review_assessment",
        },
    )


def _register_init_routes(app):
    @app.get("/api/init/status")
    async def init_status():
        return {"initialized": app.state.initialized}

    @app.get("/api/init/questionnaire")
    async def init_questionnaire():
        """Structured questionnaire options (PRD §4.2.2).

        Single source of truth is ``allspark/data/questionnaire.yaml``, shared
        with the CLI wizard. Stable keys are persisted; both localized labels
        travel with each option so switching language never depends on the
        server process's current global locale.
        """
        from allspark.adapters.init_wizard import _load_questionnaire

        questions = _load_questionnaire()
        for options in questions.values():
            if not isinstance(options, list):
                continue
            for option in options:
                label_key = option.get("label_key", "")
                option["labels"] = {
                    lang: MESSAGES.get(lang, {}).get(label_key, label_key)
                    for lang in ("zh", "en")
                }
        return {"version": "2", "questions": questions}

    @app.post("/api/init/assessment/preview")
    async def init_assessment_preview(request: Request):
        try:
            body = await request.json()
        except Exception:
            body = None
        payload = body.get("assessment") if isinstance(body, dict) else None
        language = body.get("language") if isinstance(body, dict) else None
        try:
            assessment = validate_initial_assessment(
                payload, require_confirmation=False
            )
        except InitialAssessmentValidationError as exc:
            return _assessment_error_response(exc, language)
        return {"status": "ok", "summary": assessment_preview(assessment)}

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
        survivor_name: str = Query(""),
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
        init_lock = app.state.init_lock
        if not init_lock.acquire(blocking=False):
            return JSONResponse(
                status_code=409,
                content={
                    "status": "error",
                    "error": "bootstrap_in_progress",
                    "detail": t("web_init_busy"),
                    "next_action": "retry",
                },
            )

        previous_language = get_language()
        prepared = None
        try:
            # Middleware is an early gate only. Re-check both sources while
            # holding the lock so concurrent/repeated requests cannot publish.
            if app.state.initialized or db.is_initialized():
                return JSONResponse(
                    status_code=410,
                    content={
                        "status": "error",
                        "error": "bootstrap_closed",
                        "detail": t("web_init_closed"),
                        "next_action": "",
                    },
                )
            if language not in ("zh", "en"):
                return JSONResponse(
                    status_code=422,
                    content={
                        "status": "error",
                        "error": "invalid_language",
                        "detail": t("error_invalid_language"),
                        "next_action": "choose_language",
                    },
                )
            if not survivor_name:
                survivor_name = MESSAGES.get(language, {}).get(
                    "web_init_default_survivor_name", "Survivor"
                )

            # Validate the complete safety-critical assessment before the
            # hardware/profile/registry draft performs any self-committing
            # write. Empty strings are never interpreted as unknown.
            try:
                assessment = validate_initial_assessment(body.get("assessment"))
            except InitialAssessmentValidationError as exc:
                return _assessment_error_response(exc, language)

            profile = detect_hardware()
            flags = compute_feature_flags(profile.tier, profile.gpu_available)

            # Draft writes use fixed keys and may self-commit. A retry safely
            # overwrites them, but they never imply a published installation.
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

            set_language(language, persist=False)
            prepared = _prepare_engine(app, flags=flags)

            # Candidate services own the shared Web/CLI assessment contract.
            # These fixed-key draft writes are idempotent across a failed
            # finalize and never imply a published installation.
            db.save_survivor_state("name", survivor_name)
            db.save_survivor_state("language", language)
            db.save_survivor_state("location_type", location_type)
            db.save_survivor_state("skills", skills)
            db.save_survivor_state("questionnaire_version", "3")
            assessment_service = prepared.container.require("initial_assessment")
            gap_tasks = assessment_service.apply(assessment)
            db.finalize_initialization(language)

            # Publish is deliberately synchronous and contains no fallible I/O.
            _publish_engine(app, prepared)
            app.state.initialized = True

            # SHA-142: only a fully published bootstrap receives the auth cookie.
            resp = JSONResponse(
                content={
                    "status": "ok",
                    "summary": assessment_preview(assessment),
                    "created_task_ids": [task.id for task in gap_tasks],
                }
            )
            if _WEB_TOKEN:
                _set_auth_cookie(resp, _WEB_TOKEN)
            return resp
        except Exception:
            detail = t("web_init_retryable")
            logger.exception("Initialization failed before runtime publish")
            rollback_initialization_draft(db)
            if prepared is not None:
                cleanup_application_candidate(prepared.bootstrap)
            set_language(previous_language, persist=False)
            return JSONResponse(
                status_code=503,
                content={
                    "status": "error",
                    "error": "bootstrap_failed",
                    "detail": detail,
                    "next_action": "retry",
                },
            )
        finally:
            init_lock.release()
