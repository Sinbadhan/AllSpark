import os
from pathlib import Path
from typing import Optional

from allspark.hardware import FeatureFlags, HardwareTier, LLM_MODEL_MAP
from allspark.config import DEFAULT_DB_DIR


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
            self._error = "LLM disabled by hardware flags"
            return False

        try:
            from llama_cpp import Llama
        except ImportError:
            self._error = "llama-cpp-python not installed. Run: pip install llama-cpp-python"
            return False

        model_path = self._find_model()
        if not model_path:
            model_name = self.flags.llm_model
            self._error = (
                f"Model file not found: {model_name}.gguf\n"
                f"Expected location: {LLM_MODELS_DIR}/{model_name}.gguf\n"
                f"Download from: https://huggingface.co/Qwen/Qwen2.5-{self._model_size()}-Instruct-GGUF"
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
            self._error = f"Failed to load model: {e}"
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
            return f"[LLM error: {e}]"

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
            return f"[LLM error: {e}]"

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

    def _model_size(self) -> str:
        info = LLM_MODEL_MAP.get(self.flags.tier, {})
        model = info.get("model", "Qwen2.5-3B")
        size = model.replace("Qwen2.5-", "").replace("-Q4", "")
        return size

    def get_status(self) -> dict:
        return {
            "available": self._available,
            "model_name": self.flags.llm_model,
            "model_path": self._model_path,
            "error": self._error,
        }
