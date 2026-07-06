import logging
from pathlib import Path
from typing import Optional

from allspark.core.config import DEFAULT_DB_DIR
from allspark.core.i18n import t
from allspark.infrastructure.hardware import FeatureFlags, HardwareTier

logger = logging.getLogger(__name__)

LLM_MODELS_DIR = DEFAULT_DB_DIR / "models"


class LLMEngine:
    def __init__(self, flags: FeatureFlags):
        self.flags = flags
        self._llm = None
        self._model_path: Optional[str] = None
        self._available = False
        self._error: Optional[str] = None

    @property
    def available(self) -> bool:
        return self._available

    @property
    def model_name(self) -> str:
        return self.flags.llm_model

    @property
    def error(self) -> Optional[str]:
        return self._error

    def load(self) -> bool:
        if not self.flags.llm:
            self._error = t("llm_error_disabled")
            return False

        try:
            from llama_cpp import Llama
        except ImportError:
            self._error = t("llm_error_not_installed")
            return False

        model_path = self._find_model()
        if not model_path:
            model_name = self.flags.llm_model
            download_hint = self._download_hint(model_name)
            self._error = t(
                "llm_error_model_not_found",
                model=model_name,
                path=str(LLM_MODELS_DIR),
                url=download_hint,
            )
            return False

        try:
            n_ctx = 2048
            n_gpu_layers = 0
            if self.flags.tier in (HardwareTier.COMFORTABLE, HardwareTier.FLAGSHIP):
                n_ctx = 4096

            self._llm = Llama(
                model_path=str(model_path),
                n_ctx=n_ctx,
                n_gpu_layers=n_gpu_layers,
                verbose=False,
            )
            self._model_path = str(model_path)
            self._available = True
            return True
        except Exception as e:
            self._error = t("llm_error_load_failed", error=str(e))
            logger.error(f"Failed to load LLM model: {e}")
            return False

    def chat(self, messages: list[dict], max_tokens: int = 512, temperature: float = 0.7) -> str:
        if not self._available or not self._llm:
            return ""

        try:
            response = self._llm.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return response["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"LLM chat completion failed: {e}")
            return t("llm_error_chat", error=str(e))

    def generate(self, prompt: str, max_tokens: int = 256, temperature: float = 0.7) -> str:
        if not self._available or not self._llm:
            return ""

        try:
            response = self._llm(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                echo=False,
            )
            return response["choices"][0]["text"]
        except Exception as e:
            logger.error(f"LLM generate failed: {e}")
            return t("llm_error_chat", error=str(e))

    def chat_stream(self, messages: list[dict], max_tokens: int = 512, temperature: float = 0.7):
        """Yield tokens one by one for SSE streaming."""
        if not self._available or not self._llm:
            return

        try:
            for chunk in self._llm.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
            ):
                delta = chunk["choices"][0]["delta"]
                if "content" in delta:
                    yield delta["content"]
        except Exception as e:
            logger.error(f"LLM chat stream failed: {e}")
            yield t("llm_error_chat", error=str(e))

    def survival_chat_stream(self, user_input: str, context: str = "", phase: int = 0):
        """Yield tokens for survival chat via SSE."""
        if not self._available:
            return

        system_prompt = self._build_system_prompt(phase)
        messages = [
            {"role": "system", "content": system_prompt},
        ]
        if context:
            messages.append({"role": "system", "content": f"Context:\n{context}"})
        messages.append({"role": "user", "content": user_input})

        yield from self.chat_stream(messages, max_tokens=512, temperature=0.7)

    def survival_chat(self, user_input: str, context: str = "", phase: int = 0) -> str:
        if not self._available:
            return ""

        system_prompt = self._build_system_prompt(phase)
        messages = [
            {"role": "system", "content": system_prompt},
        ]
        if context:
            messages.append({"role": "system", "content": f"Context:\n{context}"})
        messages.append({"role": "user", "content": user_input})

        return self.chat(messages, max_tokens=512, temperature=0.7)

    def _build_system_prompt(self, phase: int) -> str:
        phase_names = {
            0: "immediate survival (0-72h)",
            1: "short-term survival (1-30 days)",
            2: "mid-term self-sufficiency (1-12 months)",
            3: "quality of life (1-5 years)",
            4: "civilization renaissance (5+ years)",
        }
        return (
            "You are AllSpark (火种), an offline AI survival system. "
            "Your mission is to help survivors stay alive and rebuild civilization.\n"
            f"Current survival phase: {phase_names.get(phase, 'unknown')}\n"
            "Rules:\n"
            "- Prioritize survival above all else\n"
            "- Give practical, actionable advice\n"
            "- Be concise in emergencies, detailed when stable\n"
            "- If unsure, say so and suggest verification\n"
            "- Respond in the same language as the user's input\n"
        )

    def _find_model(self) -> Optional[Path]:
        model_name = self.flags.llm_model
        LLM_MODELS_DIR.mkdir(parents=True, exist_ok=True)

        candidates = [
            LLM_MODELS_DIR / f"{model_name}.gguf",
            LLM_MODELS_DIR / f"{model_name}-Q4_K_M.gguf",
            LLM_MODELS_DIR / f"{model_name.lower()}.gguf",
        ]

        for path in candidates:
            if path.exists():
                return path

        for f in LLM_MODELS_DIR.glob("*.gguf"):
            if model_name.lower().replace("-", "").replace(".", "") in f.stem.lower().replace("-", "").replace(".", ""):
                return f

        return None

    def _download_hint(self, model_name: str) -> str:
        """Best-effort download URL for ``model_name`` from the catalog;
        falls back to the HuggingFace search page when the model is not
        in the catalog (custom user .gguf)."""
        try:
            from allspark.services import model_registry
            entry = model_registry.get_model(model_name)
            return entry.url_mirror or entry.url_hf
        except (KeyError, ImportError):
            return f"https://huggingface.co/models?search={model_name}"

    def get_status(self) -> dict:
        return {
            "available": self._available,
            "model_name": self.flags.llm_model,
            "model_path": self._model_path,
            "error": self._error,
        }
