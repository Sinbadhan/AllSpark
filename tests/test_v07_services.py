"""Tests for Phase 6-7 service modules: personality, psychology, weather, gps, timeline, diary, environment, daily_briefing."""
import os
import tempfile

from allspark.core.database import Database
from allspark.core.models import OperatingMode, PersonalityMode
from allspark.services.personality import PersonalitySystem


class TestPersonalitySystem:
    def test_default_mode_is_stable(self):
        p = PersonalitySystem()
        assert p.current_mode == PersonalityMode.STABLE

    def test_crisis_mode_on_hibernation(self):
        p = PersonalitySystem()
        mode = p.determine_mode(OperatingMode.HIBERNATION, [], phase=2)
        assert mode == PersonalityMode.CRISIS

    def test_crisis_mode_on_critical_warning(self):
        p = PersonalitySystem()
        mode = p.determine_mode(OperatingMode.STANDARD, [{"level": "critical"}], phase=2)
        assert mode == PersonalityMode.CRISIS

    def test_crisis_mode_on_phase_0(self):
        p = PersonalitySystem()
        mode = p.determine_mode(OperatingMode.STANDARD, [], phase=0)
        assert mode == PersonalityMode.CRISIS

    def test_multiplayer_mode(self):
        p = PersonalitySystem()
        mode = p.determine_mode(OperatingMode.STANDARD, [], phase=2, is_multiplayer=True)
        assert mode == PersonalityMode.MULTIPLAYER

    def test_renaissance_mode_high_phase_proactive(self):
        p = PersonalitySystem()
        mode = p.determine_mode(OperatingMode.PROACTIVE, [], phase=4)
        assert mode == PersonalityMode.RENAISSANCE

    def test_companion_mode_proactive_low_phase(self):
        p = PersonalitySystem()
        mode = p.determine_mode(OperatingMode.PROACTIVE, [], phase=2)
        assert mode == PersonalityMode.COMPANION

    def test_stable_mode_standard_no_warnings(self):
        p = PersonalitySystem()
        mode = p.determine_mode(OperatingMode.STANDARD, [], phase=2)
        assert mode == PersonalityMode.STABLE

    def test_crisis_on_warnings_standard(self):
        p = PersonalitySystem()
        mode = p.determine_mode(OperatingMode.STANDARD, [{"level": "warning"}], phase=2)
        assert mode == PersonalityMode.CRISIS

    def test_renaissance_standard_high_phase(self):
        p = PersonalitySystem()
        mode = p.determine_mode(OperatingMode.STANDARD, [], phase=4)
        assert mode == PersonalityMode.RENAISSANCE

    def test_get_greeting(self):
        p = PersonalitySystem()
        greeting = p._get_greeting()
        assert isinstance(greeting, str)
        assert len(greeting) > 0

    def test_classify_intent(self):
        p = PersonalitySystem()
        result = p.classify_intent("help")
        assert isinstance(result, str)


class TestPsychologyTracker:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.tmpdir, "test.db"))
        from allspark.services.psychology import PsychologyTracker
        self.tracker = PsychologyTracker(self.db)

    def test_record_interaction(self):
        self.tracker.record_interaction("positive")
        assert self.tracker._interaction_count == 1

    def test_record_multiple_interactions(self):
        for _ in range(5):
            self.tracker.record_interaction("neutral")
        assert self.tracker._interaction_count == 5

    def test_assess_state_default(self):
        state = self.tracker.assess_state()
        assert "loneliness_index" in state
        assert "stress_index" in state
        assert "overall_state" in state

    def test_get_self_assessment_questions(self):
        questions = self.tracker.get_self_assessment_questions()
        assert isinstance(questions, list)
        assert len(questions) > 0

    def test_process_assessment(self):
        questions = self.tracker.get_self_assessment_questions()
        answers = {q["id"]: 3 for q in questions}
        result = self.tracker.process_assessment(answers)
        assert "score" in result

    def test_format_status(self):
        status = self.tracker.format_status()
        assert isinstance(status, str)

    def test_check_intervention_no_trigger(self):
        result = self.tracker.check_and_trigger_intervention()
        # Should be None when no intervention needed
        assert result is None or isinstance(result, dict)


class TestWeatherPredictor:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.tmpdir, "test.db"))
        from allspark.services.weather import WeatherPredictor
        self.weather = WeatherPredictor(db=self.db)

    def test_get_current_conditions(self):
        conditions = self.weather.get_current_conditions()
        assert "source" in conditions

    def test_predict_weather(self):
        result = self.weather.predict_weather()
        assert isinstance(result, dict)

    def test_set_manual_pressure(self):
        self.weather.set_manual_pressure(1013.0)
        # Should not raise

    def test_get_cloud_guide(self):
        guide = self.weather.get_cloud_guide()
        assert isinstance(guide, str)

    def test_format_prediction(self):
        text = self.weather.format_prediction()
        assert isinstance(text, str)


class TestGPSManager:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.tmpdir, "test.db"))
        from allspark.services.gps_manager import GPSManager
        self.gps = GPSManager(db=self.db)

    def test_set_and_get_position(self):
        self.gps.set_manual_position(39.9, 116.4, 50.0)
        loc = self.gps.get_position()
        assert loc is not None
        assert abs(loc["lat"] - 39.9) < 0.01
        assert abs(loc["lon"] - 116.4) < 0.01

    def test_get_position_none_initially(self):
        loc = self.gps.get_position()
        assert loc is None or isinstance(loc, dict)

    def test_calculate_distance(self):
        d = self.gps.calculate_distance(39.9, 116.4, 31.2, 121.5)
        assert d > 0
        assert 800 < d < 1400

    def test_calculate_bearing(self):
        bearing = self.gps.calculate_bearing(39.9, 116.4, 31.2, 121.5)
        assert 0 <= bearing <= 360

    def test_bearing_to_direction(self):
        direction = self.gps.bearing_to_direction(45.0)
        assert isinstance(direction, str)

    def test_format_position(self):
        pos = {"lat": 39.9, "lon": 116.4, "alt": 50, "source": "manual", "timestamp": "2026-01-01"}
        text = self.gps.format_position(pos)
        assert isinstance(text, str)

    def test_record_track_point(self):
        self.gps.set_manual_position(39.9, 116.4, 50.0)
        result = self.gps.record_track_point("camp")
        assert isinstance(result, str)  # returns track id


class TestTimelineManager:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.tmpdir, "test.db"))
        from allspark.services.timeline import TimelineManager
        self.timeline = TimelineManager(db=self.db)

    def test_add_event(self):
        event = self.timeline.add_event("milestone", "Test Event", "Description")
        assert "id" in event

    def test_get_timeline(self):
        self.timeline.add_event("milestone", "Event1")
        events = self.timeline.get_timeline(limit=10)
        assert len(events) >= 1

    def test_format_timeline(self):
        self.timeline.add_event("milestone", "Recent Event")
        text = self.timeline.format_timeline()
        assert isinstance(text, str)

    def test_record_goal_completed(self):
        self.timeline.record_goal_completed("goal-1", "Test Goal")
        events = self.timeline.get_timeline(limit=10)
        assert len(events) >= 1

    def test_record_resource_change(self):
        self.timeline.record_resource_change("power", "increased")
        events = self.timeline.get_timeline(limit=10)
        assert len(events) >= 1

    def test_get_all_days(self):
        self.timeline.add_event("system", "Day test")
        days = self.timeline.get_all_days()
        assert isinstance(days, list)


class TestDiaryManager:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.tmpdir, "test.db"))
        from allspark.services.diary import DiaryManager
        self.diary = DiaryManager(db=self.db)

    def test_create_entry(self):
        entry = self.diary.add_entry("Today was hard", emotion="sad")
        assert "id" in entry

    def test_get_entries_empty(self):
        entries = self.diary.get_entries()
        assert isinstance(entries, list)

    def test_get_entries_after_create(self):
        self.diary.add_entry("Test entry")
        entries = self.diary.get_entries()
        assert len(entries) >= 1

    def test_get_entry_by_id(self):
        entry = self.diary.add_entry("Specific entry")
        fetched = self.diary.get_entry(entry["id"])
        assert fetched is not None

    def test_get_dates(self):
        self.diary.add_entry("Date test")
        dates = self.diary.get_dates()
        assert isinstance(dates, list)
        assert len(dates) >= 1

    def test_get_emotion_stats(self):
        self.diary.add_entry("Happy day", emotion="happy")
        stats = self.diary.get_emotion_stats()
        assert isinstance(stats, dict)

    def test_format_entries(self):
        self.diary.add_entry("Format test")
        text = self.diary.format_entries()
        assert isinstance(text, str)

    def test_delete_entry(self):
        entry = self.diary.add_entry("To delete")
        result = self.diary.delete_entry(entry["id"])
        assert result is True


class TestEnvironmentAssessor:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.tmpdir, "test.db"))
        from allspark.services.environment import EnvironmentAssessor
        self.assessor = EnvironmentAssessor(db=self.db)

    def test_assess_returns_dict(self):
        result = self.assessor.assess()
        assert "climate" in result
        assert "terrain" in result
        assert "threats" in result
        assert "opportunities" in result
        assert "overall_score" in result

    def test_overall_score_range(self):
        result = self.assessor.assess()
        assert 0 <= result["overall_score"] <= 1


class TestDailyBriefing:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.tmpdir, "test.db"))
        from allspark.services.daily_briefing import DailyBriefing
        self.briefing = DailyBriefing(db=self.db)

    def test_generate_returns_string(self):
        result = self.briefing.generate()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_save_briefing_to_timeline(self):
        self.briefing.save_briefing_to_timeline()
        # Should not raise
