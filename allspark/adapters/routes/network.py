"""Network and Vision API routes."""

from pathlib import Path

from fastapi import HTTPException, Query

from allspark.adapters.routes.helpers import _get_service, _require_service, error_response
from allspark.core.config import DEFAULT_DB_DIR
from allspark.core.i18n import t
from allspark.services.vision_engine import VisionTask

_SAFE_MEDIA_DIR = DEFAULT_DB_DIR / "media"


def _safe_media_path(path: str) -> str:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = _SAFE_MEDIA_DIR / candidate
    safe_root = _SAFE_MEDIA_DIR.resolve()
    resolved = candidate.resolve(strict=False)
    if safe_root != resolved and safe_root not in resolved.parents:
        raise HTTPException(400, "Vision image paths must stay under ~/.allspark/media")
    if not resolved.exists():
        raise HTTPException(404, "Image file not found")
    return str(resolved)


def register_network_routes(app, check):
    @app.get("/api/network/status")
    async def network_status():
        container, db = check()
        network_svc = _require_service(app, 'spark_network')
        return network_svc.get_status()

    @app.post("/api/network/scan")
    async def network_scan():
        container, db = check()
        network_svc = _require_service(app, 'spark_network')
        return network_svc.detect_channels()

    @app.post("/api/network/start")
    async def network_start():
        container, db = check()
        network_svc = _require_service(app, 'spark_network')
        result = network_svc.start_discovery()
        if result["status"] == "started":
            network_svc.start_exchange_server()
        return result

    @app.post("/api/network/stop")
    async def network_stop():
        network_svc = _get_service(app, 'spark_network')
        if network_svc is not None:
            return network_svc.stop_discovery()
        return {"status": "not_running"}

    @app.post("/api/network/exchange")
    async def network_exchange(node_id: str = Query(...)):
        network_svc = _get_service(app, 'spark_network')
        if network_svc is not None:
            return network_svc.request_exchange(node_id)
        return error_response(t("error_network_not_started"), next_action=t("error_start_network_first"))

    @app.post("/api/network/send")
    async def network_send(node_id: str = Query(...), entry_ids: str = Query(...)):
        network_svc = _get_service(app, 'spark_network')
        if network_svc is not None:
            ids = [x.strip() for x in entry_ids.split(",")]
            return network_svc.send_knowledge(node_id, ids)
        return error_response(t("error_network_not_started"), next_action=t("error_start_network_first"))

    @app.get("/api/vision/status")
    async def vision_status():
        container, db = check()
        vision_svc = _require_service(app, 'vision_engine')
        return vision_svc.get_status()

    @app.post("/api/vision/analyze")
    async def vision_analyze(
        image_path: str = Query(...),
        task: str = Query("general"),
    ):
        container, db = check()
        vision_svc = _require_service(app, 'vision_engine')
        try:
            vtask = VisionTask(task)
        except ValueError:
            vtask = VisionTask.GENERAL
        image_path = _safe_media_path(image_path)
        result = vision_svc.analyze_image(image_path, vtask)
        return result.to_dict()
