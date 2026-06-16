"""Survival API routes: goals, briefing, timeline, diary, gps, reset, psych."""

from fastapi import Request

from allspark.adapters.routes.helpers import _get_service, error_response, service_unavailable
from allspark.core.i18n import render, t


def register_survival_routes(app, check):
    @app.get("/api/goals")
    async def api_goals():
        """Get all active goals"""
        goal_engine_svc = _get_service(app, 'goal_engine')
        if goal_engine_svc is None:
            return service_unavailable("goal_engine", app=app)
        goals = goal_engine_svc.get_active_goals()
        return {"goals": [
            {
                "id": g.id, "title": render(g.title), "description": render(g.description),
                "priority": g.priority, "status": g.status, "progress": g.progress,
                "category": g.category, "milestone_done": g.milestone_done,
                "milestone_count": g.milestone_count, "deadline": g.deadline,
            } for g in goals
        ]}

    @app.get("/api/goals/{goal_id}")
    async def api_goal_detail(goal_id: str):
        """Get goal details"""
        goal_engine_svc = _get_service(app, 'goal_engine')
        if goal_engine_svc is None:
            return service_unavailable("goal_engine", app=app)
        goal = goal_engine_svc.db.get_goal(goal_id)
        if not goal:
            return error_response(t("error_goal_not_found"), detail=t("error_goal_not_found_detail", goal_id=goal_id))
        milestones = goal_engine_svc.db.get_milestones_by_goal(goal_id)
        return {
            "goal": {
                "id": goal.id, "title": render(goal.title), "description": render(goal.description),
                "priority": goal.priority, "status": goal.status, "progress": goal.progress,
                "category": goal.category, "source": goal.source,
                "milestone_done": goal.milestone_done, "milestone_count": goal.milestone_count,
                "deadline": goal.deadline, "rationale": goal.rationale,
            },
            "milestones": [
                {"id": m.id, "description": render(m.description), "done": m.done, "order": m.order}
                for m in milestones
            ],
        }

    @app.post("/api/goals/add")
    async def api_add_goal(request: Request):
        """Manually add a goal"""
        goal_engine_svc = _get_service(app, 'goal_engine')
        if goal_engine_svc is None:
            return service_unavailable("goal_engine", app=app)
        data = await request.json()
        goal = goal_engine_svc.add_manual_goal(
            title=data.get("title", ""),
            description=data.get("description", ""),
            priority=data.get("priority", "medium"),
            category=data.get("category", "survival"),
        )
        return {"goal": {"id": goal.id, "title": render(goal.title)}}

    @app.post("/api/goals/{goal_id}/complete")
    async def api_complete_goal(goal_id: str):
        """Complete a goal"""
        goal_engine_svc = _get_service(app, 'goal_engine')
        if goal_engine_svc is None:
            return service_unavailable("goal_engine", app=app)
        success = goal_engine_svc.complete_goal(goal_id)
        return {"success": success}

    @app.post("/api/milestones/{milestone_id}/complete")
    async def api_complete_milestone(milestone_id: str):
        """Complete a milestone"""
        goal_engine_svc = _get_service(app, 'goal_engine')
        if goal_engine_svc is None:
            return service_unavailable("goal_engine", app=app)
        success = goal_engine_svc.complete_milestone(milestone_id)
        return {"success": success}

    @app.get("/api/briefing")
    async def api_briefing():
        """Get daily briefing"""
        daily_briefing_svc = _get_service(app, 'daily_briefing')
        if daily_briefing_svc is None:
            return service_unavailable("daily_briefing", app=app)
        briefing = daily_briefing_svc.generate()
        return {"briefing": briefing}

    @app.get("/api/briefing/short")
    async def api_briefing_short():
        """Get short briefing"""
        daily_briefing_svc = _get_service(app, 'daily_briefing')
        if daily_briefing_svc is None:
            return service_unavailable("daily_briefing", app=app)
        briefing = daily_briefing_svc.generate_short()
        return {"briefing": briefing}

    @app.get("/api/timeline")
    async def api_timeline(day: int = None, limit: int = 50):
        """Get timeline"""
        timeline_svc = _get_service(app, 'timeline')
        if timeline_svc is None:
            return service_unavailable("timeline", app=app)
        events = timeline_svc.get_timeline(day=day, limit=limit)
        return {"events": [
            {
                "id": e["id"], "day": e["day"], "timestamp": e["timestamp"],
                "event_type": e["event_type"], "title": render(e["title"]),
                "description": render(e["description"]), "emotion": e["emotion"],
            } for e in events
        ]}

    @app.get("/api/timeline/recent")
    async def api_timeline_recent(days: int = 7):
        """Get recent timeline"""
        timeline_svc = _get_service(app, 'timeline')
        if timeline_svc is None:
            return service_unavailable("timeline", app=app)
        events = timeline_svc.get_timeline(limit=max(days * 10, 20))
        text = timeline_svc.format_timeline(events)
        return {"timeline": text}

    @app.get("/api/diary")
    async def api_diary(date: str = None):
        """Get diary entries"""
        diary_svc = _get_service(app, 'diary')
        if diary_svc is None:
            return service_unavailable("diary", app=app)
        entries = diary_svc.get_entries(date=date, limit=20)
        return {"entries": [
            {
                "id": e["id"], "date": e["date"], "content": e["content"],
                "emotion": e["emotion"], "keywords": e["keywords"],
            } for e in entries
        ]}

    @app.post("/api/diary/add")
    async def api_add_diary(request: Request):
        """Add diary entry"""
        diary_svc = _get_service(app, 'diary')
        if diary_svc is None:
            return service_unavailable("diary", app=app)
        data = await request.json()
        entry = diary_svc.add_entry(
            content=data.get("content", ""),
            emotion=data.get("emotion", "neutral"),
            related_goal_id=data.get("related_goal_id", ""),
        )
        return {"entry": {"id": entry["id"], "date": entry["date"]}}

    @app.get("/api/diary/review")
    async def api_diary_review(days: int = 7):
        """Diary review"""
        diary_svc = _get_service(app, 'diary')
        if diary_svc is None:
            return service_unavailable("diary", app=app)
        entries = diary_svc.get_entries(limit=max(days * 3, 10))
        text = diary_svc.format_entries(entries, limit=len(entries))
        return {"review": text}

    @app.get("/api/gps")
    async def api_gps():
        """Get GPS location"""
        gps_manager_svc = _get_service(app, 'gps_manager')
        if gps_manager_svc is None:
            return service_unavailable("gps_manager", app=app)
        loc = gps_manager_svc.get_position()
        return {"location": loc}

    @app.post("/api/gps/set")
    async def api_set_gps(request: Request):
        """Set GPS location"""
        gps_manager_svc = _get_service(app, 'gps_manager')
        if gps_manager_svc is None:
            return service_unavailable("gps_manager", app=app)
        data = await request.json()
        # Accept both canonical ("latitude"/"longitude") and shorthand ("lat"/"lng").
        lat = data.get("latitude", data.get("lat", 0))
        lon = data.get("longitude", data.get("lng", 0))
        alt = data.get("altitude", data.get("alt", 0))
        # Type validation — reject non-numeric values early.
        try:
            lat = float(lat)
            lon = float(lon)
            alt = float(alt)
        except (TypeError, ValueError):
            return error_response(
                t("error_gps_invalid"),
                detail="Latitude and longitude must be numeric values.",
            )
        if not (-90 <= lat <= 90):
            return error_response(t("error_gps_invalid"), detail=t("error_gps_lat_range"))
        if not (-180 <= lon <= 180):
            return error_response(t("error_gps_invalid"), detail=t("error_gps_lng_range"))
        location = gps_manager_svc.set_manual_position(lat, lon, alt)
        return {"success": True, "location": location}

    @app.get("/api/gps/nearby")
    async def api_gps_nearby(radius_km: float = 5.0):
        """Get nearby POIs"""
        gps_manager_svc = _get_service(app, 'gps_manager')
        if gps_manager_svc is None:
            return service_unavailable("gps_manager", app=app)
        nearby = [p for p in gps_manager_svc.annotate_pois_with_distance() if p.get("distance_km", 0) <= radius_km]
        return {"nearby": nearby}

    @app.post("/api/reset/{level}")
    async def api_reset(level: int, request: Request):
        """Perform system reset"""
        reset_manager_svc = _get_service(app, 'reset_manager')
        if reset_manager_svc is None:
            return service_unavailable("reset_manager", app=app)
        # Body may be missing/empty (e.g. fetch without payload). Don't 500.
        try:
            data = await request.json()
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        confirm = data.get("confirm", False)
        if not confirm:
            return error_response(
                "Confirmation required",
                detail="Reset requires explicit confirmation to prevent accidental data loss.",
                next_action="Send confirm=true in the request body.",
            )

        from allspark.core.models import ResetLevel
        level_map = {1: ResetLevel.ASSESSMENT, 2: ResetLevel.ARCHIVE, 3: ResetLevel.FACTORY}
        reset_level = level_map.get(level)
        if reset_level is None:
            return error_response(
                "Invalid reset level",
                detail=f"Level {level} is not valid.",
                next_action="Use level 1 (assessment), 2 (archive), or 3 (factory reset).",
            )
        result = reset_manager_svc.execute_reset(reset_level, force=bool(data.get("force", False)))
        ok = result.get("status") == "ok"

        # FACTORY reset wipes the operating_state row that marks the system as
        # initialized, but the FastAPI app keeps `app.state.initialized=True`
        # in process memory. Without this re-sync, the user lands on the
        # dashboard instead of the init wizard after L3.
        if not ok:
            reasons = result.get("reason") or []
            reason_text = reasons[0] if isinstance(reasons, list) and reasons else str(reasons) if reasons else "Reset rejected"
            return error_response(
                "Reset rejected",
                detail=reason_text,
                status=409,
            )

        if reset_level == ResetLevel.FACTORY and ok:
            container, db = check()
            app.state.initialized = db.is_initialized()
            app.state.engine = None

        # Surface the rejection reason(s) the manager produced. Without this
        # the UI shows "rejected" with no clue (regression: B-3 — cooldown,
        # hibernation, emergency-state blocks all looked the same).
        response: dict = {
            "success": ok,
            "status": result.get("status", ""),
            "message": result.get("status", ""),
        }
        reasons = result.get("reason") or []
        if isinstance(reasons, list) and reasons:
            response["reasons"] = reasons
            response["error"] = reasons[0] if isinstance(reasons[0], str) else str(reasons[0])
        elif isinstance(reasons, str) and reasons:
            response["error"] = reasons
        return response

    @app.get("/api/psych")
    async def api_psych():
        """Get psychological state"""
        psych_tracker_svc = _get_service(app, 'psychology')
        if psych_tracker_svc is None:
            return service_unavailable("psychology", app=app)
        return {"state": psych_tracker_svc.assess_state()}

    @app.get("/api/reset/logs")
    async def api_reset_logs(limit: int = 10):
        """Get reset logs"""
        reset_manager_svc = _get_service(app, 'reset_manager')
        if reset_manager_svc is None:
            return service_unavailable("reset_manager", app=app)
        return {"logs": reset_manager_svc.db.get_reset_logs(limit)}

    # ---------------- Psychology questionnaire ----------------

    @app.get("/api/psych/questions")
    async def api_psych_questions():
        """List the self-assessment questions."""
        psych = _get_service(app, 'psychology')
        if psych is None:
            return service_unavailable("psychology", app=app)
        return {"questions": psych.get_self_assessment_questions()}

    @app.post("/api/psych/assessment")
    async def api_psych_assessment(request: Request):
        """Submit answers (dict of question_id -> int score) and get a result."""
        psych = _get_service(app, 'psychology')
        if psych is None:
            return service_unavailable("psychology", app=app)
        try:
            body = await request.json()
        except Exception:
            body = {}
        answers = body.get("answers", body) if isinstance(body, dict) else {}
        if not isinstance(answers, dict):
            return error_response(t("error_answers_must_be_dict"), detail=t("error_answers_format"))
        try:
            normalized = {k: int(v) for k, v in answers.items()}
        except (TypeError, ValueError):
            return error_response("Scores must be integers")
        return psych.process_assessment(normalized)

    # ---------------- Weather ----------------

    @app.get("/api/weather")
    async def api_weather():
        weather = _get_service(app, 'weather')
        if weather is None:
            return service_unavailable("weather", app=app)
        return {
            "current": weather.get_current_conditions(),
            "forecast": weather.predict_weather(),
            "guide": weather.get_cloud_guide(),
        }

    @app.post("/api/weather/pressure")
    async def api_weather_pressure(request: Request):
        weather = _get_service(app, 'weather')
        if weather is None:
            return service_unavailable("weather", app=app)
        body = await _safe_json(request)
        try:
            hpa = float(body.get("pressure", body.get("hpa", 0)))
        except (TypeError, ValueError):
            return error_response("pressure must be a number")
        weather.set_manual_pressure(hpa)
        return {"status": "ok", "pressure_hpa": hpa}

    # ---------------- Environment ----------------

    @app.get("/api/environment")
    async def api_environment():
        env = _get_service(app, 'environment')
        if env is None:
            return service_unavailable("environment", app=app)
        return env.assess()

    # ---------------- Map / POI ----------------

    @app.get("/api/map/poi")
    async def api_map_list():
        m = _get_service(app, 'map_system')
        if m is None:
            return service_unavailable("map_system", app=app)
        pois = m.get_all()
        return {"pois": [_poi_dict(p) for p in pois]}

    @app.post("/api/map/poi")
    async def api_map_add(request: Request):
        m = _get_service(app, 'map_system')
        if m is None:
            return service_unavailable("map_system", app=app)
        body = await _safe_json(request)
        name = (body.get("name") or "").strip()
        poi_type = (body.get("type") or body.get("poi_type") or "general").strip()
        if not name:
            return error_response("name required")
        try:
            poi = m.add_poi(
                name=name,
                poi_type=poi_type,
                description=body.get("description", ""),
                lat=body.get("lat"),
                lon=body.get("lon"),
            )
        except TypeError:
            # older signature: positional
            poi = m.add_poi(name, poi_type, body.get("description", ""))
        return {"status": "ok", "poi": _poi_dict(poi)}

    @app.delete("/api/map/poi/{poi_id}")
    async def api_map_remove(poi_id: str):
        m = _get_service(app, 'map_system')
        if m is None:
            return service_unavailable("map_system", app=app)
        m.remove_poi(poi_id)
        return {"status": "ok", "id": poi_id}


# Module-level helpers (kept here so they don't bloat the closure)


async def _safe_json(request: Request) -> dict:
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


def _poi_dict(poi) -> dict:
    if poi is None:
        return {}
    if isinstance(poi, dict):
        return poi
    return {
        "id": getattr(poi, "id", None),
        "name": getattr(poi, "name", ""),
        "type": getattr(poi, "type", ""),
        "description": getattr(poi, "description", ""),
        "lat": getattr(poi, "lat", None),
        "lon": getattr(poi, "lon", None),
    }
