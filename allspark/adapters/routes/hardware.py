"""Hardware API routes: power, sensor, preserve."""

from fastapi import Query

from allspark.adapters.routes.helpers import _require_service


def register_hardware_routes(app, check):
    @app.get("/api/power/status")
    async def power_status():
        container, db = check()
        power_svc = _require_service(app, 'power_monitor')
        return power_svc.get_status()

    @app.post("/api/power/monitor/start")
    async def power_monitor_start(interval: int = Query(60)):
        container, db = check()
        power_svc = _require_service(app, 'power_monitor')
        return power_svc.start_monitoring(interval)

    @app.post("/api/power/monitor/stop")
    async def power_monitor_stop():
        container, db = check()
        power_svc = _require_service(app, 'power_monitor')
        return power_svc.stop_monitoring()

    @app.post("/api/power/manual")
    async def power_manual(
        energy_wh: float = Query(...),
        charging: bool = Query(False),
    ):
        container, db = check()
        power_svc = _require_service(app, 'power_monitor')
        return power_svc.manual_input(energy_wh, charging)

    @app.get("/api/power/runtime")
    async def power_runtime():
        container, db = check()
        power_svc = _require_service(app, 'power_monitor')
        return power_svc.estimate_runtime()

    @app.get("/api/power/history")
    async def power_history(last_n: int = Query(100)):
        container, db = check()
        power_svc = _require_service(app, 'power_monitor')
        return {"readings": power_svc.get_history(last_n)}

    @app.get("/api/sensor/status")
    async def sensor_status():
        container, db = check()
        sensor_svc = _require_service(app, 'sensor_hub')
        return sensor_svc.get_status()

    @app.get("/api/sensor/devices")
    async def sensor_devices():
        container, db = check()
        sensor_svc = _require_service(app, 'sensor_hub')
        return {"devices": sensor_svc.get_all_devices()}

    @app.post("/api/sensor/device/add")
    async def sensor_device_add(
        name: str = Query(...),
        sensor_type: str = Query("temperature"),
    ):
        container, db = check()
        sensor_svc = _require_service(app, 'sensor_hub')
        device = sensor_svc.register_device(name, sensor_type)
        return {"status": "ok", "device": {"name": device.name, "type": device.sensor_type, "interface": device.interface}}

    @app.post("/api/sensor/poll/start")
    async def sensor_poll_start():
        container, db = check()
        sensor_svc = _require_service(app, 'sensor_hub')
        return sensor_svc.start_polling()

    @app.post("/api/sensor/poll/stop")
    async def sensor_poll_stop():
        container, db = check()
        sensor_svc = _require_service(app, 'sensor_hub')
        return sensor_svc.stop_polling()

    @app.get("/api/sensor/snapshot")
    async def sensor_snapshot():
        container, db = check()
        sensor_svc = _require_service(app, 'sensor_hub')
        snap = sensor_svc.get_snapshot()
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
        container, db = check()
        sensor_svc = _require_service(app, 'sensor_hub')
        return {"detected": sensor_svc.auto_detect()}

    @app.get("/api/preserve/status")
    async def preserve_status():
        container, db = check()
        preserve_svc = _require_service(app, 'data_preservation')
        return preserve_svc.get_status()

    @app.post("/api/preserve/auto-save/start")
    async def preserve_auto_start(interval: int = Query(300)):
        container, db = check()
        preserve_svc = _require_service(app, 'data_preservation')
        return preserve_svc.start_auto_save(interval)

    @app.post("/api/preserve/auto-save/stop")
    async def preserve_auto_stop():
        container, db = check()
        preserve_svc = _require_service(app, 'data_preservation')
        return preserve_svc.stop_auto_save()

    @app.post("/api/preserve/emergency")
    async def preserve_emergency():
        container, db = check()
        preserve_svc = _require_service(app, 'data_preservation')
        return preserve_svc.emergency_save("web_api")

    @app.post("/api/preserve/snapshot")
    async def preserve_snapshot(label: str = Query("")):
        container, db = check()
        preserve_svc = _require_service(app, 'data_preservation')
        return preserve_svc.create_snapshot(label)

    @app.get("/api/preserve/snapshots")
    async def preserve_snapshots():
        container, db = check()
        preserve_svc = _require_service(app, 'data_preservation')
        return {"snapshots": preserve_svc.list_snapshots()}

    @app.post("/api/preserve/restore")
    async def preserve_restore(label: str = Query(...), confirm: str = Query("")):
        """Restore a snapshot. Requires confirm='RESET' to prevent accidents."""
        container, db = check()
        if confirm != "RESET":
            from allspark.adapters.routes.helpers import error_response
            return error_response(
                "Confirmation required",
                detail="Restore overwrites the current database. "
                       "Add ?confirm=RESET to acknowledge this is intentional.",
                next_action="Re-issue the request with ?confirm=RESET.",
            )
        preserve_svc = _require_service(app, 'data_preservation')
        return preserve_svc.restore_snapshot(label)
