import pytest

from allspark.core.database import Database
from allspark.core.models import Goal, Resource, ResourceType
from allspark.services.daily_briefing import DailyBriefing
from allspark.services.diary import DiaryManager
from allspark.services.psychology import PsychologyTracker
from allspark.services.timeline import TimelineManager
from allspark.services.weather import WeatherPredictor


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


class TestDailyBriefing:
    def test_generate_briefing(self, db):
        briefing = DailyBriefing(db=db)
        result = briefing.generate()
        assert isinstance(result, str)
        assert len(result) > 0
        assert "火种" in result or "AllSpark" in result or "简报" in result

    def test_generate_with_resources(self, db):
        r = Resource(
            type=ResourceType.POWER, current_amount=100.0, unit="Wh",
            daily_consumption=50.0, daily_intake=0.0,
            estimated_remaining_hours=48.0, last_updated="",
        )
        db.upsert_resource(r)
        briefing = DailyBriefing(db=db)
        result = briefing.generate()
        assert "power" in result.lower() or "电力" in result or "100" in result

    def test_generate_with_goals(self, db):
        from allspark.services.goal_engine import GoalEngine
        goal = Goal(
            id="test-g1", title="Find water", goal_type="auto",
            category="survival", priority="critical", status="active",
            source="assessment", created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )
        db.save_goal(goal)
        ge = GoalEngine(db=db)
        briefing = DailyBriefing(db=db, goal_engine=ge)
        result = briefing.generate()
        assert "Find water" in result or "目标" in result


class TestTimeline:
    def test_add_event(self, db):
        tl = TimelineManager(db=db)
        result = tl.add_event("system_event", "System initialized")
        assert "id" in result
        assert result["title"] == "System initialized"

    def test_get_timeline(self, db):
        tl = TimelineManager(db=db)
        tl.add_event("system_event", "Event 1")
        tl.add_event("system_event", "Event 2")
        events = tl.get_timeline()
        assert len(events) == 2

    def test_format_timeline(self, db):
        tl = TimelineManager(db=db)
        tl.add_event("system_event", "Test event")
        output = tl.format_timeline()
        assert "时间线" in output or "Test event" in output

    def test_record_goal_completed(self, db):
        tl = TimelineManager(db=db)
        result = tl.record_goal_completed("g1", "Find water")
        assert result["event_type"] == "goal_completed"

    def test_day_summary(self, db):
        tl = TimelineManager(db=db)
        tl.add_event("system_event", "Day event")
        summary = tl.get_day_summary(1)
        assert "event_count" in summary


class TestDiary:
    def test_add_entry(self, db):
        dm = DiaryManager(db=db)
        result = dm.add_entry(content="Today was a hard day", emotion="negative")
        assert result["id"]
        assert result["content_length"] > 0

    def test_get_entries(self, db):
        dm = DiaryManager(db=db)
        dm.add_entry("Entry 1", emotion="positive")
        dm.add_entry("Entry 2", emotion="neutral")
        entries = dm.get_entries()
        assert len(entries) == 2

    def test_delete_entry(self, db):
        dm = DiaryManager(db=db)
        result = dm.add_entry("To delete")
        assert dm.delete_entry(result["id"]) is True
        assert dm.get_entry(result["id"]) is None

    def test_emotion_stats(self, db):
        dm = DiaryManager(db=db)
        dm.add_entry("Happy", emotion="positive")
        dm.add_entry("Sad", emotion="negative")
        dm.add_entry("Meh", emotion="neutral")
        stats = dm.get_emotion_stats()
        assert stats["total_entries"] == 3
        assert stats["positive"] == 1
        assert stats["negative"] == 1

    def test_diary_with_timeline(self, db):
        tl = TimelineManager(db=db)
        dm = DiaryManager(db=db, timeline=tl)
        dm.add_entry("Test with timeline", emotion="positive")
        events = tl.get_timeline(event_type="diary_entry")
        assert len(events) == 1

    def test_format_entries(self, db):
        dm = DiaryManager(db=db)
        dm.add_entry("A test diary entry that is long enough to be meaningful")
        output = dm.format_entries()
        assert "日记" in output or "diary" in output.lower()


class TestWeather:
    def test_predict_clear(self, db):
        wp = WeatherPredictor(db=db)
        conditions = {"pressure_hpa": 1030.0, "pressure_trend": "rising"}
        prediction = wp.predict_weather(conditions)
        assert prediction["forecast"] == "clear"
        assert prediction["confidence"] > 0

    def test_predict_storm(self, db):
        wp = WeatherPredictor(db=db)
        conditions = {"pressure_hpa": 980.0, "pressure_trend": "falling"}
        prediction = wp.predict_weather(conditions)
        assert prediction["forecast"] == "storm_likely"
        assert prediction["severity"] == "severe"

    def test_predict_rain(self, db):
        wp = WeatherPredictor(db=db)
        conditions = {"pressure_hpa": 990.0, "pressure_trend": "falling"}
        prediction = wp.predict_weather(conditions)
        assert prediction["forecast"] == "rain_likely"

    def test_predict_no_data(self, db):
        wp = WeatherPredictor(db=db)
        conditions = {"pressure_hpa": None}
        prediction = wp.predict_weather(conditions)
        assert prediction["forecast"] == "no_data"

    def test_format_prediction(self, db):
        wp = WeatherPredictor(db=db)
        conditions = {"pressure_hpa": 1015.0, "pressure_trend": "stable"}
        output = wp.format_prediction(conditions)
        assert "天气" in output or "Weather" in output

    def test_cloud_guide(self, db):
        wp = WeatherPredictor(db=db)
        guide = wp.get_cloud_guide()
        assert "云" in guide or "cloud" in guide.lower()


class TestPsychology:
    def test_assess_state(self, db):
        pt = PsychologyTracker(db=db)
        assessment = pt.assess_state()
        assert "loneliness_index" in assessment
        assert "stress_index" in assessment
        assert "overall_state" in assessment
        assert 0 <= assessment["loneliness_index"] <= 1.0
        assert 0 <= assessment["stress_index"] <= 1.0

    def test_record_interaction(self, db):
        pt = PsychologyTracker(db=db)
        pt.record_interaction("positive")
        assessment = pt.assess_state()
        assert assessment["loneliness_index"] < 0.5

    def test_self_assessment_questions(self, db):
        pt = PsychologyTracker(db=db)
        questions = pt.get_self_assessment_questions()
        assert len(questions) == 5
        assert all("id" in q and "question" in q for q in questions)

    def test_process_assessment_good(self, db):
        pt = PsychologyTracker(db=db)
        answers = {"sleep": 0, "appetite": 0, "mood": 0, "social": 0, "hope": 0}
        result = pt.process_assessment(answers)
        assert result["score"] < 0.3
        assert result["needs_intervention"] is False

    def test_process_assessment_bad(self, db):
        pt = PsychologyTracker(db=db)
        answers = {"sleep": 2, "appetite": 2, "mood": 2, "social": 2, "hope": 2}
        result = pt.process_assessment(answers)
        assert result["score"] > 0.5
        assert result["needs_intervention"] is True

    def test_format_status(self, db):
        pt = PsychologyTracker(db=db)
        output = pt.format_status()
        assert "心理" in output or "Mental" in output
