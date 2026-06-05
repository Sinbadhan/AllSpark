"""Network and Vision API routes."""

from fastapi import Query

from allspark.adapters.routes.helpers import _get_service, _require_service


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
        if _get_service(app, 'spark_network') is not None:
            return app.state.network.stop_discovery()
        return {"status": "not_running"}

    @app.post("/api/network/exchange")
    async def network_exchange(node_id: str = Query(...)):
        if _get_service(app, 'spark_network') is not None:
            return app.state.network.request_exchange(node_id)
        return {"status": "error", "message": "Network not started"}

    @app.post("/api/network/send")
    async def network_send(node_id: str = Query(...), entry_ids: str = Query(...)):
        if _get_service(app, 'spark_network') is not None:
            ids = [x.strip() for x in entry_ids.split(",")]
            return app.state.network.send_knowledge(node_id, ids)
        return {"status": "error", "message": "Network not started"}

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
        from allspark.services.vision_engine import VisionTask
        try:
            vtask = VisionTask(task)
        except ValueError:
            vtask = VisionTask.GENERAL
        result = vision_svc.analyze_image(image_path, vtask)
        return result.to_dict()
