import pytest

from allspark.voice import VoiceManager


class TestVoiceManager:
    def test_status(self):
        vm = VoiceManager()
        status = vm.get_status()
        assert "stt_available" in status
        assert "tts_available" in status
        assert "is_listening" in status

    def test_format_status(self):
        vm = VoiceManager()
        output = vm.format_status()
        assert "语音" in output or "Voice" in output

    def test_transcribe_without_model(self):
        vm = VoiceManager()
        result = vm.transcribe("/nonexistent/audio.wav")
        assert result["status"] == "error"
        assert "not loaded" in result["message"]

    def test_transcribe_from_mic_without_model(self):
        vm = VoiceManager()
        result = vm.transcribe_from_mic()
        assert result["status"] == "error"

    def test_speak_without_tts(self):
        vm = VoiceManager()
        result = vm.speak("test")
        if result["status"] == "error":
            assert "not installed" in result["message"] or "error" in result["message"].lower()

    def test_voice_diary_without_model(self):
        vm = VoiceManager()
        result = vm.voice_diary()
        assert result["status"] == "error"

    def test_load_whisper_missing(self):
        vm = VoiceManager()
        result = vm.load_whisper()
        if result["status"] == "error":
            assert "not installed" in result["message"] or "error" in result["message"].lower()
