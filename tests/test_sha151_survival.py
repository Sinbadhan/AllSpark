"""SHA-151: survival commands line-coverage tests (criterion 1: total line >=75%).

Exercises the 8 survival command classes (briefing/timeline/diary/weather/
psychology/gps/environment/voice) with mocked services + console.input.
"""
from unittest.mock import MagicMock

from allspark.commands.survival import (
    BriefingCommand,
    DiaryCommand,
    EnvironmentCommand,
    GPSCommand,
    PsychologyCommand,
    TimelineCommand,
    VoiceCommand,
    WeatherCommand,
)


def _svc(svc=None):
    """Return (container, service); service is a fresh MagicMock if not given."""
    c = MagicMock()
    if svc is None:
        svc = MagicMock()
    c.get.return_value = svc
    return c, svc


def _no_svc():
    c = MagicMock()
    c.get.return_value = None
    return c


def _run(Cls, args, container):
    Cls(container).execute(args)


# ─── Briefing ────────────────────────────────────────────────────────────────


def test_briefing_not_loaded():
    _run(BriefingCommand, [], _no_svc())


def test_briefing_generates():
    c, svc = _svc()
    svc.generate.return_value = "brief"
    _run(BriefingCommand, [], c)


# ─── Timeline ────────────────────────────────────────────────────────────────


def test_timeline_not_loaded():
    _run(TimelineCommand, [], _no_svc())


def test_timeline_no_args():
    c, svc = _svc()
    svc.format_timeline.return_value = "tl"
    _run(TimelineCommand, [], c)


def test_timeline_day_with_events_and_without():
    c, svc = _svc()
    svc.get_day_summary.side_effect = [
        {"event_count": 1, "events": [{"x": 1}]},
        {"event_count": 0, "events": []},
    ]
    svc.format_timeline.return_value = "formatted"
    _run(TimelineCommand, ["day", "1"], c)
    _run(TimelineCommand, ["天", "2"], c)


def test_timeline_day_invalid_number():
    c, _ = _svc()
    _run(TimelineCommand, ["day", "abc"], c)


def test_timeline_add_with_and_without_title():
    c, _ = _svc()
    _run(TimelineCommand, ["add", "my", "event"], c)
    _run(TimelineCommand, ["add"], c)  # no title -> early return


def test_timeline_unknown_sub():
    c, _ = _svc()
    _run(TimelineCommand, ["unknown"], c)


# ─── Diary ───────────────────────────────────────────────────────────────────


def test_diary_not_loaded():
    _run(DiaryCommand, [], _no_svc())


def test_diary_no_args_lists():
    c, svc = _svc()
    svc.format_entries.return_value = "entries"
    _run(DiaryCommand, [], c)


def test_diary_add_with_content(monkeypatch):
    c, svc = _svc()
    svc.add_entry.return_value = {"id": "d1", "content_length": 5}
    cmd = DiaryCommand(c)
    inputs = iter(["hello", "END"])
    monkeypatch.setattr(cmd.console, "input", lambda *a, **k: next(inputs))
    cmd.execute(["add"])


def test_diary_add_empty_not_saved(monkeypatch):
    c, _ = _svc()
    cmd = DiaryCommand(c)
    monkeypatch.setattr(cmd.console, "input", lambda *a, **k: "END")
    cmd.execute(["add"])


def test_diary_view_by_id_found_and_not():
    c, svc = _svc()
    svc.get_entry.side_effect = [MagicMock(), None]
    svc.format_entry_detail.return_value = "detail"
    _run(DiaryCommand, ["view", "d1"], c)
    _run(DiaryCommand, ["view", "missing"], c)


def test_diary_view_list_when_no_id():
    c, svc = _svc()
    svc.get_entries.return_value = []
    svc.format_entries.return_value = "list"
    _run(DiaryCommand, ["view"], c)


def test_diary_delete_found_and_not():
    c, svc = _svc()
    svc.delete_entry.side_effect = [True, False]
    _run(DiaryCommand, ["delete", "d1"], c)
    _run(DiaryCommand, ["delete", "missing"], c)


def test_diary_emotion_stats():
    c, svc = _svc()
    svc.get_emotion_stats.return_value = {
        "total_entries": 5, "positive": 2, "neutral": 2, "negative": 1, "positive_ratio": 0.4,
    }
    _run(DiaryCommand, ["emotion"], c)


def test_diary_unknown_sub():
    c, _ = _svc()
    _run(DiaryCommand, ["unknown"], c)


# ─── Weather ─────────────────────────────────────────────────────────────────


def test_weather_not_loaded():
    _run(WeatherCommand, [], _no_svc())


def test_weather_no_args():
    c, svc = _svc()
    svc.format_prediction.return_value = "forecast"
    _run(WeatherCommand, [], c)


def test_weather_cloud_and_pressure():
    c, svc = _svc()
    svc.get_cloud_guide.return_value = "clouds"
    _run(WeatherCommand, ["cloud"], c)
    _run(WeatherCommand, ["pressure", "1013"], c)  # valid
    _run(WeatherCommand, ["pressure", "abc"], c)  # invalid


def test_weather_unknown_sub():
    c, _ = _svc()
    _run(WeatherCommand, ["unknown"], c)


# ─── Psychology ──────────────────────────────────────────────────────────────


def test_psychology_not_loaded():
    _run(PsychologyCommand, [], _no_svc())


def test_psychology_no_args():
    c, svc = _svc()
    svc.format_status.return_value = "status"
    _run(PsychologyCommand, [], c)


def test_psychology_assess(monkeypatch):
    c, svc = _svc()
    svc.get_self_assessment_questions.return_value = [
        {"id": "q1", "question": "How?", "options": ["a", "b"]}
    ]
    svc.process_assessment.return_value = {"score": 5, "state": "ok", "advice": "rest"}
    cmd = PsychologyCommand(c)
    monkeypatch.setattr(cmd.console, "input", lambda *a, **k: "1")
    cmd.execute(["assess"])


def test_psychology_unknown_sub():
    c, _ = _svc()
    _run(PsychologyCommand, ["unknown"], c)


# ─── GPS ──────────────────────────────────────────────────────────────────────


def test_gps_not_loaded():
    _run(GPSCommand, [], _no_svc())


def test_gps_no_args():
    c, svc = _svc()
    svc.format_position.return_value = "pos"
    _run(GPSCommand, [], c)


def test_gps_set_valid_and_invalid():
    c, _ = _svc()
    _run(GPSCommand, ["set", "40.5", "-74.0"], c)
    _run(GPSCommand, ["set", "abc", "def"], c)


def test_gps_track_and_record():
    c, svc = _svc()
    svc.format_track.return_value = "track"
    svc.record_track_point.side_effect = [{"lat": 40}, None]  # ok then no position
    _run(GPSCommand, ["track"], c)
    _run(GPSCommand, ["record", "label"], c)  # ok
    _run(GPSCommand, ["record"], c)  # no position


def test_gps_distance_valid_and_invalid():
    c, svc = _svc()
    svc.calculate_distance.return_value = 100.0
    svc.calculate_bearing.return_value = 90.0
    svc.bearing_to_direction.return_value = "E"
    _run(GPSCommand, ["distance", "40", "-74", "41", "-73"], c)
    _run(GPSCommand, ["distance", "a", "b", "c", "d"], c)


def test_gps_unknown_sub():
    c, _ = _svc()
    _run(GPSCommand, ["unknown"], c)


# ─── Environment ──────────────────────────────────────────────────────────────


def test_environment_not_loaded():
    _run(EnvironmentCommand, [], _no_svc())


def test_environment_assessment():
    c, svc = _svc()
    svc.format_assessment.return_value = "env"
    _run(EnvironmentCommand, [], c)


# ─── Voice ────────────────────────────────────────────────────────────────────


def test_voice_not_loaded():
    _run(VoiceCommand, [], _no_svc())


def test_voice_no_args():
    c, svc = _svc()
    svc.format_status.return_value = "status"
    _run(VoiceCommand, [], c)


def test_voice_load_ok_and_fail():
    c, svc = _svc()
    svc.load_whisper.side_effect = [{"status": "ok"}, {"status": "error", "message": "no model"}]
    _run(VoiceCommand, ["load", "base"], c)
    _run(VoiceCommand, ["load"], c)


def test_voice_transcribe_with_path_and_mic():
    c, svc = _svc()
    svc.transcribe.return_value = {"status": "ok", "language": "zh", "text": "hi"}
    svc.transcribe_from_mic.return_value = {"status": "error", "message": "no mic"}
    _run(VoiceCommand, ["transcribe", "/path.wav"], c)
    _run(VoiceCommand, ["transcribe"], c)  # from mic, fails


def test_voice_speak_ok_and_fail():
    c, svc = _svc()
    svc.speak.side_effect = [{"status": "ok"}, {"status": "error", "message": "no tts"}]
    _run(VoiceCommand, ["speak", "hello"], c)
    _run(VoiceCommand, ["speak"], c)


def test_voice_diary_ok_and_fail():
    c, svc = _svc()
    svc.voice_diary.side_effect = [
        {"status": "ok", "text": "diary", "diary_entry": {"id": "v1"}},
        {"status": "error", "message": "no mic"},
    ]
    _run(VoiceCommand, ["diary"], c)
    _run(VoiceCommand, ["diary"], c)


def test_voice_unknown_sub():
    c, _ = _svc()
    _run(VoiceCommand, ["unknown"], c)
