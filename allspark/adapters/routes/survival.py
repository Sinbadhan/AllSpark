"""Survival API routes: goals, briefing, timeline, diary, gps, reset, psych."""

from datetime import datetime, timedelta

from fastapi import Request

from allspark.adapters.routes.helpers import _get_service


def register_survival_routes(app, check):
    @app.get("/api/goals")
    async def api_goals():
        """Get all active goals"""
        goal_engine_svc = _get_service(app, 'goal_engine')
        if goal_engine_svc is None:
            return {"error": "Goal engine not loaded", "goals": []}
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
            return {"error": "Goal engine not loaded"}
        goal = goal_engine_svc.get_goal(goal_id)
        if not goal:
            return {"error": "Goal not found"}
        milestones = goal_engine_svc.get_milestones(goal_id)
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
            return {"error": "Goal engine not loaded"}
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
            return {"error": "Goal engine not loaded"}
        success = goal_engine_svc.complete_goal(goal_id)
        return {"success": success}

    @app.post("/api/milestones/{milestone_id}/complete")
    async def api_complete_milestone(milestone_id: str):
        """Complete a milestone"""
        goal_engine_svc = _get_service(app, 'goal_engine')
        if goal_engine_svc is None:
            return {"error": "Goal engine not loaded"}
        success = goal_engine_svc.complete_milestone(milestone_id)
        return {"success": success}

    @app.get("/api/briefing")
    async def api_briefing():
        """Get daily briefing"""
        daily_briefing_svc = _get_service(app, 'daily_briefing')
        if daily_briefing_svc is None:
            return {"error": "Briefing module not loaded"}
        briefing = daily_briefing_svc.generate()
        return {"briefing": briefing}

    @app.get("/api/briefing/short")
    async def api_briefing_short():
        """Get short briefing"""
        daily_briefing_svc = _get_service(app, 'daily_briefing')
        if daily_briefing_svc is None:
            return {"error": "Briefing module not loaded"}
        briefing = daily_briefing_svc.generate_short()
        return {"briefing": briefing}

    @app.get("/api/timeline")
    async def api_timeline(day: int = None, limit: int = 50):
        """Get timeline"""
        timeline_svc = _get_service(app, 'timeline')
        if timeline_svc is None:
            return {"error": "Timeline module not loaded"}
        events = timeline_svc.get_events(day=day, limit=limit)
        return {"events": [
            {
                "id": e.id, "day": e.day, "timestamp": e.timestamp,
                "event_type": e.event_type, "title": e.title,
                "description": e.description, "emotion": e.emotion,
            } for e in events
        ]}

    @app.get("/api/timeline/recent")
    async def api_timeline_recent(days: int = 7):
        """Get recent timeline"""
        timeline_svc = _get_service(app, 'timeline')
        if timeline_svc is None:
            return {"error": "Timeline module not loaded"}
        text = timeline_svc.format_recent(days=days)
        return {"timeline": text}

    @app.get("/api/diary")
    async def api_diary(date: str = None):
        """Get diary entries"""
        diary_svc = _get_service(app, 'diary')
        if diary_svc is None:
            return {"error": "Diary module not loaded"}
        if date:
            entries = diary_svc.get_by_date(date)
        else:
            latest = diary_svc.get_latest()
            entries = [latest] if latest else []
        return {"entries": [
            {
                "id": e.id, "date": e.date, "content": e.content,
                "emotion": e.emotion, "keywords": e.keywords,
            } for e in entries
        ]}

    @app.post("/api/diary/add")
    async def api_add_diary(request: Request):
        """Add diary entry"""
        diary_svc = _get_service(app, 'diary')
        if diary_svc is None:
            return {"error": "Diary module not loaded"}
        data = await request.json()
        entry = diary_svc.create_entry(
            content=data.get("content", ""),
            related_goal_id=data.get("related_goal_id", ""),
        )
        return {"entry": {"id": entry.id, "date": entry.date}}

    @app.get("/api/diary/review")
    async def api_diary_review(days: int = 7):
        """Diary review"""
        diary_svc = _get_service(app, 'diary')
        if diary_svc is None:
            return {"error": "Diary module not loaded"}
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        entries = diary_svc.get_range(start_date, end_date)
        text = diary_svc.format_review(entries, days=days)
        return {"review": text}

    @app.get("/api/gps")
    async def api_gps():
        """Get GPS location"""
        gps_manager_svc = _get_service(app, 'gps_manager')
        if gps_manager_svc is None:
            return {"error": "GPS module not loaded", "location": None}
        loc = gps_manager_svc.get_location()
        return {"location": loc}

    @app.post("/api/gps/set")
    async def api_set_gps(request: Request):
        """Set GPS location"""
        gps_manager_svc = _get_service(app, 'gps_manager')
        if gps_manager_svc is None:
            return {"error": "GPS module not loaded"}
        data = await request.json()
        lat = data.get("latitude", 0)
        lon = data.get("longitude", 0)
        alt = data.get("altitude", 0)
        gps_manager_svc.set_location(lat, lon, alt)
        return {"success": True, "location": gps_manager_svc.get_location()}

    @app.get("/api/gps/nearby")
    async def api_gps_nearby(radius_km: float = 5.0):
        """Get nearby POIs"""
        gps_manager_svc = _get_service(app, 'gps_manager')
        if gps_manager_svc is None:
            return {"error": "GPS module not loaded", "nearby": []}
        nearby = gps_manager_svc.get_nearby_pois(radius_km=radius_km)
        return {"nearby": [
            {
                "poi": {"id": item["poi"].id, "name": item["poi"].name, "type": item["poi"].type},
                "distance_km": item["distance_km"],
            } for item in nearby
        ]}

    @app.post("/api/reset/{level}")
    async def api_reset(level: int, request: Request):
        """Perform system reset"""
        reset_manager_svc = _get_service(app, 'reset_manager')
        if reset_manager_svc is None:
            return {"error": "Reset manager not loaded"}
        data = await request.json()
        confirm = data.get("confirm", False)
        if not confirm:
            return {"error": "Confirmation required. Send confirm=true"}

        if level == 1:
            result = reset_manager_svc.reset_assessment()
        elif level == 2:
            result = reset_manager_svc.reset_archive()
        elif level == 3:
            password = data.get("password", "")
            result = reset_manager_svc.reset_factory(password)
        else:
            return {"error": "Invalid reset level (1/2/3)"}

        return {"success": result.get("success", False), "message": result.get("message", "")}

    @app.get("/api/psych")
    async def api_psych():
        """Get psychological state"""
        psych_tracker_svc = _get_service(app, 'psychology')
        if psych_tracker_svc is None:
            return {"error": "Psych tracker not loaded"}
        latest = psych_tracker_svc.get_latest()
        return {"state": latest}

    @app.get("/api/reset/logs")
    async def api_reset_logs(limit: int = 10):
        """Get reset logs"""
        reset_manager_svc = _get_service(app, 'reset_manager')
        if reset_manager_svc is None:
            return {"error": "Reset manager not loaded"}
        logs = reset_manager_svc.get_logs(limit=limit)
        return {"logs": logs}
