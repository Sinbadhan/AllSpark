import os
import wave
import tempfile
from datetime import datetime
from typing import Optional


class VoiceManager:
    def __init__(self, db=None, diary=None, llm_engine=None):
        self.db = db
        self.diary = diary
        self.llm_engine = llm_engine
        self._whisper_model = None
        self._tts_engine = None
        self._is_listening = False

    def is_stt_available(self) -> bool:
        try:
            import whisper
            return True
        except ImportError:
            return False

    def is_tts_available(self) -> bool:
        try:
            import pyttsx3
            return True
        except ImportError:
            return False

    def get_status(self) -> dict:
        return {
            "stt_available": self.is_stt_available(),
            "tts_available": self.is_tts_available(),
            "whisper_model": self._whisper_model is not None,
            "is_listening": self._is_listening,
        }

    def load_whisper(self, model_name: str = "base") -> dict:
        try:
            import whisper
            self._whisper_model = whisper.load_model(model_name)
            return {"status": "ok", "model": model_name}
        except ImportError:
            return {"status": "error", "message": "whisper not installed. Run: pip install openai-whisper"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def transcribe(self, audio_path: str, language: str = None) -> dict:
        if not self._whisper_model:
            return {"status": "error", "message": "Whisper model not loaded. Use 'voice load' first."}

        if not os.path.exists(audio_path):
            return {"status": "error", "message": f"Audio file not found: {audio_path}"}

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
            import numpy as np
        except ImportError:
            return {
                "status": "error",
                "message": "sounddevice not installed. Run: pip install sounddevice",
            }

        if not self._whisper_model:
            return {"status": "error", "message": "Whisper model not loaded."}

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
                "message": "pyttsx3 not installed. Run: pip install pyttsx3",
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

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
            return {"status": "error", "message": "No speech detected"}

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
            "🎙️ 语音交互",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"  语音识别(STT)：{'✅ 可用' if status['stt_available'] else '❌ 未安装 (pip install openai-whisper)'}",
            f"  语音合成(TTS)：{'✅ 可用' if status['tts_available'] else '❌ 未安装 (pip install pyttsx3)'}",
            f"  Whisper 模型：{'✅ 已加载' if status['whisper_model'] else '❌ 未加载'}",
            f"  监听状态：{'🟢 监听中' if status['is_listening'] else '⚪ 未启动'}",
        ]

        if not status["stt_available"] and not status["tts_available"]:
            lines.append("")
            lines.append("  💡 安装语音支持：")
            lines.append("    pip install openai-whisper sounddevice")
            lines.append("    pip install pyttsx3")

        return "\n".join(lines)
