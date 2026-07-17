import importlib.util
import os
import tempfile
import threading
import uuid
import wave
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from allspark.core.i18n import t


@dataclass
class VoiceSession:
    """Multi-turn voice conversation session."""
    session_id: str = field(default_factory=lambda: f"voice-{uuid.uuid4().hex[:8]}")
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    turn_count: int = 0
    messages: list[dict] = field(default_factory=list)
    timeout_minutes: int = 5

    def is_active(self) -> bool:
        return datetime.now() - self.last_activity < timedelta(minutes=self.timeout_minutes)

    def add_turn(self, role: str, content: str):
        self.messages.append({"role": role, "content": content, "ts": datetime.now().isoformat()})
        self.turn_count += 1
        self.last_activity = datetime.now()

    def get_context(self, max_turns: int = 10) -> list[dict]:
        return [{"role": m["role"], "content": m["content"]} for m in self.messages[-max_turns:]]


class VADRecorder:
    """Offline VAD recorder wrapper.

    The real continuous audio loop requires optional deps (`sounddevice`, `webrtcvad`).
    This class provides a safe interface and graceful degradation.
    """

    def __init__(self, on_audio=None, sample_rate: int = 16000):
        self.on_audio = on_audio
        self.sample_rate = sample_rate
        self.running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def is_available(self) -> bool:
        return (
            importlib.util.find_spec("sounddevice") is not None
            and importlib.util.find_spec("webrtcvad") is not None
        )

    def start(self) -> dict:
        if not self.is_available():
            return {"status": "error", "message": t("voice_error_sd_webrtcvad_not_installed")}
        if self.running:
            return {"status": "ok", "message": "already running"}
        self.running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="allspark-vad")
        self._thread.start()
        return {"status": "ok"}

    def stop(self):
        self.running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    def _loop(self):
        # Conservative placeholder: actual VAD stream is dependency-specific.
        # Keeps the lifecycle testable and safe on machines without audio devices.
        while not self._stop_event.wait(0.5):
            pass


class VoiceManager:
    def __init__(
        self,
        db=None,
        diary=None,
        llm_engine=None,
        dispatcher=None,
        crisis_support=None,
    ):
        self.db = db
        self.diary = diary
        self.llm_engine = llm_engine
        self.dispatcher = dispatcher
        self.crisis_support = crisis_support
        self._whisper_model = None
        self._tts_engine = None
        self._is_listening = False
        self._session: VoiceSession | None = None
        self._vad: VADRecorder | None = None
        self.wake_words: tuple[str, ...] = ("hey spark", "allspark", "火种")

    def is_stt_available(self) -> bool:
        return importlib.util.find_spec("whisper") is not None

    def is_tts_available(self) -> bool:
        return importlib.util.find_spec("pyttsx3") is not None

    def is_vad_available(self) -> bool:
        return VADRecorder().is_available()

    def get_status(self) -> dict:
        return {
            "stt_available": self.is_stt_available(),
            "tts_available": self.is_tts_available(),
            "vad_available": self.is_vad_available(),
            "whisper_model": self._whisper_model is not None,
            "is_listening": self._is_listening,
            "session_active": self._session.is_active() if self._session else False,
            "session_turns": self._session.turn_count if self._session else 0,
        }

    def load_whisper(self, model_name: str = "base") -> dict:
        try:
            import whisper
            self._whisper_model = whisper.load_model(model_name)
            return {"status": "ok", "model": model_name}
        except ImportError:
            return {"status": "error", "message": t("voice_error_whisper_not_installed")}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def transcribe(self, audio_path: str, language: str = None) -> dict:
        if not self._whisper_model:
            return {"status": "error", "message": t("voice_error_whisper_not_loaded")}

        if not os.path.exists(audio_path):
            return {"status": "error", "message": t("voice_error_audio_not_found", path=audio_path)}

        try:
            options = {}
            if language:
                options["language"] = language

            result = self._whisper_model.transcribe(audio_path, **options)
            text = result.get("text", "").strip()

            detected_lang = result.get("language", "unknown")

            return {
                "status": "ok",
                "text": text,
                "language": detected_lang,
                "segments": len(result.get("segments", [])),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def transcribe_from_mic(self, duration: int = 5, language: str = None) -> dict:
        try:
            import sounddevice as sd
        except ImportError:
            return {
                "status": "error",
                "message": t("voice_error_sounddevice_not_installed"),
            }

        if not self._whisper_model:
            return {"status": "error", "message": t("voice_error_whisper_not_loaded_short")}

        try:
            fs = 16000
            recording = sd.rec(int(duration * fs), samplerate=fs, channels=1, dtype='int16')
            sd.wait()

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_path = f.name
                with wave.open(tmp_path, 'w') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(fs)
                    wf.writeframes(recording.tobytes())

            result = self.transcribe(tmp_path, language=language)
            os.unlink(tmp_path)
            return result

        except Exception as e:
            return {"status": "error", "message": str(e)}

    def speak(self, text: str) -> dict:
        try:
            import pyttsx3
            if self._tts_engine is None:
                self._tts_engine = pyttsx3.init()
            self._tts_engine.say(text)
            self._tts_engine.runAndWait()
            return {"status": "ok", "text": text}
        except ImportError:
            return {
                "status": "error",
                "message": t("voice_error_pyttsx3_not_installed"),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─── Continuous Voice Interaction ───────────────────────────────────

    def start_continuous_listening(self, wake_word: str = "hey spark") -> dict:
        """Start continuous VAD-based listening loop."""
        if wake_word and wake_word not in self.wake_words:
            self.wake_words = (wake_word, *self.wake_words)
        self._vad = VADRecorder(on_audio=self._handle_audio_segment)
        result = self._vad.start()
        self._is_listening = result.get("status") == "ok"
        return result

    def stop_listening(self) -> dict:
        if self._vad:
            self._vad.stop()
        self._is_listening = False
        return {"status": "ok"}

    def handle_voice_input(self, text: str) -> str:
        """Route transcribed text to command dispatcher or LLM chat."""
        text = (text or "").strip()
        if not text:
            return t("voice_no_speech")

        command_text = self._strip_wake_word(text)
        if command_text is None:
            return t("voice_wake_word_required")

        session = self._get_or_create_session()

        if self.crisis_support:
            safety = self.crisis_support.process(
                command_text,
                conversation_id=session.session_id,
            )
            if safety is not None:
                response = self.crisis_support.format_result(safety)
                return response

        session.add_turn("user", command_text)

        # Command dispatch: first token as command, rest as args.
        if self.dispatcher:
            parts = command_text.split()
            if parts and self.dispatcher.dispatch(parts[0], parts[1:]):
                response = t("voice_command_executed")
                session.add_turn("assistant", response)
                return response

        # LLM fallback for open conversation.
        if self.llm_engine and getattr(self.llm_engine, "available", False):
            response = self.llm_engine.survival_chat(command_text)
        else:
            response = t("voice_no_llm_response")
        session.add_turn("assistant", response)
        return response

    def speak_response(self, text: str) -> dict:
        return self.speak(text)

    def _handle_audio_segment(self, audio_path: str):
        result = self.transcribe(audio_path)
        if result.get("status") == "ok":
            response = self.handle_voice_input(result.get("text", ""))
            self.speak_response(response)

    def _strip_wake_word(self, text: str) -> str | None:
        lowered = text.lower()
        for wake in self.wake_words:
            if lowered.startswith(wake.lower()):
                return text[len(wake):].strip() or text
        # If a session is already active, allow follow-up without wake word.
        if self._session and self._session.is_active():
            return text
        return None

    def _get_or_create_session(self) -> VoiceSession:
        if not self._session or not self._session.is_active():
            if self._session:
                self._session.messages.clear()
            self._session = VoiceSession()
        return self._session

    def voice_diary(self, audio_path: str = None, duration: int = 10,
                    emotion: str = "neutral") -> dict:
        if audio_path:
            result = self.transcribe(audio_path)
        else:
            result = self.transcribe_from_mic(duration)

        if result.get("status") != "ok":
            return result

        text = result["text"]
        if not text:
            return {"status": "error", "message": t("voice_no_speech")}

        if self.diary:
            entry = self.diary.add_entry(content=text, emotion=emotion)
            return {
                "status": "ok",
                "text": text,
                "diary_entry": entry,
            }

        return {"status": "ok", "text": text}

    def format_status(self) -> str:
        status = self.get_status()

        lines = [
            t("voice_header"),
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            t("voice_stt_status", status=t("field_available") if status['stt_available'] else t("voice_not_installed", pkg="openai-whisper")),
            t("voice_tts_status", status=t("field_available") if status['tts_available'] else t("voice_not_installed", pkg="pyttsx3")),
            t("voice_whisper_status", status=t("voice_loaded") if status['whisper_model'] else t("voice_not_loaded")),
            t("voice_listening_status", status=t("voice_listening") if status['is_listening'] else t("voice_not_listening")),
        ]

        if not status["stt_available"] and not status["tts_available"]:
            lines.append("")
            lines.append(t("voice_install_hint"))
            lines.append("    pip install openai-whisper sounddevice")
            lines.append("    pip install pyttsx3")

        return "\n".join(lines)
