"""Tests for complete voice interaction: VoiceSession, VADRecorder, routing."""

from unittest.mock import MagicMock

from allspark.services.voice import VADRecorder, VoiceManager, VoiceSession


class TestVoiceSession:
    def test_new_session_active(self):
        s = VoiceSession()
        assert s.is_active() is True
        assert s.turn_count == 0

    def test_add_turn_updates_context(self):
        s = VoiceSession()
        s.add_turn("user", "hello")
        s.add_turn("assistant", "hi")
        assert s.turn_count == 2
        ctx = s.get_context()
        assert ctx[0]["role"] == "user"
        assert ctx[1]["content"] == "hi"

    def test_context_limits_turns(self):
        s = VoiceSession()
        for i in range(12):
            s.add_turn("user", str(i))
        ctx = s.get_context(max_turns=5)
        assert len(ctx) == 5
        assert ctx[0]["content"] == "7"


class TestVADRecorder:
    def test_availability_bool(self):
        r = VADRecorder()
        assert isinstance(r.is_available(), bool)

    def test_start_gracefully_without_deps(self):
        r = VADRecorder()
        result = r.start()
        assert result["status"] in ("ok", "error")
        r.stop()


class TestVoiceManagerRouting:
    def test_wake_word_required_without_session(self):
        vm = VoiceManager()
        result = vm.handle_voice_input("status")
        assert isinstance(result, str)

    def test_wake_word_stripped(self):
        vm = VoiceManager()
        stripped = vm._strip_wake_word("hey spark status")
        assert stripped == "status"

    def test_active_session_allows_followup(self):
        vm = VoiceManager()
        vm._get_or_create_session()
        stripped = vm._strip_wake_word("status")
        assert stripped == "status"

    def test_dispatcher_command_execution(self):
        dispatcher = MagicMock()
        dispatcher.dispatch.return_value = True
        vm = VoiceManager(dispatcher=dispatcher)
        response = vm.handle_voice_input("hey spark status")
        assert response
        dispatcher.dispatch.assert_called_once_with("status", [])

    def test_llm_fallback_when_no_command(self):
        llm = MagicMock()
        llm.available = True
        llm.survival_chat.return_value = "LLM response"
        vm = VoiceManager(llm_engine=llm)
        response = vm.handle_voice_input("hey spark tell me something")
        assert response == "LLM response"

    def test_start_stop_listening(self):
        vm = VoiceManager()
        result = vm.start_continuous_listening()
        assert result["status"] in ("ok", "error")
        stop = vm.stop_listening()
        assert stop["status"] == "ok"
