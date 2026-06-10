"""Survival API routes: goals, briefing, timeline, diary, gps, reset, psych."""

from fastapi import Request

from allspark.adapters.routes.helpers import _get_service, error_response, service_unavailable


def register_survival_routes(app, check):
    @app.get("/api/goals")
    async def api_goals():
        """Get all active goals"""
        goal_engine_svc = _get_service(app, 'goal_engine')
        if goal_engine_svc is None:
            return {**service_unavailable("goal_engine", app=app), "goals": []}
        goals = goal_engine_svc.get_active_goals()
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
        """Get goal details"""
        goal_engine_svc = _get_service(app, 'goal_engine')
        if goal_engine_svc is None:
            return service_unavailable("goal_engine", app=app)
        goal = goal_engine_svc.db.get_goal(goal_id)
        if not goal:
            return error_response("Goal not found", detail=f"No goal with id '{goal_id}'.")
        milestones = goal_engine_svc.db.get_milestones_by_goal(goal_id)
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
        return {"goal": {"id": goal.id, "title": goal.title}}

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
                "event_type": e["event_type"], "title": e["title"],
                "description": e["description"], "emotion": e["emotion"],
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
            return {**service_unavailable("gps_manager", app=app), "location": None}
        loc = gps_manager_svc.get_position()
        return {"location": loc}

    @app.post("/api/gps/set")
    async def api_set_gps(request: Request):
        """Set GPS location"""
        gps_manager_svc = _get_service(app, 'gps_manager')
        if gps_manager_svc is None:
            return service_unavailable("gps_manager", app=app)
        data = await request.json()
        lat = data.get("latitude", 0)
        lon = data.get("longitude", 0)
        alt = data.get("altitude", 0)
        location = gps_manager_svc.set_manual_position(lat, lon, alt)
        return {"success": True, "location": location}

    @app.get("/api/gps/nearby")
    async def api_gps_nearby(radius_km: float = 5.0):
        """Get nearby POIs"""
        gps_manager_svc = _get_service(app, 'gps_manager')
        if gps_manager_svc is None:
            return {**service_unavailable("gps_manager", app=app), "nearby": []}
        nearby = [p for p in gps_manager_svc.annotate_pois_with_distance() if p.get("distance_km", 0) <= radius_km]
        return {"nearby": nearby}

    @app.post("/api/reset/{level}")
    async def api_reset(level: int, request: Request):
        """Perform system reset"""
        reset_manager_svc = _get_service(app, 'reset_manager')
        if reset_manager_svc is None:
            return service_unavailable("reset_manager", app=app)
        data = await request.json()
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

        return {"success": result.get("status") == "ok", "message": result.get("status", "")}

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
