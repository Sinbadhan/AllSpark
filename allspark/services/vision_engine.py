import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class VisionTask(Enum):
    PLANT_IDENTIFY = "plant_identify"
    WOUND_ASSESS = "wound_assess"
    HAZARD_DETECT = "hazard_detect"
    SHELTER_EVAL = "shelter_eval"
    WATER_SOURCE = "water_source"
    TOOL_IDENTIFY = "tool_identify"
    GENERAL = "general"


@dataclass
class VisionResult:
    task: VisionTask
    description: str
    confidence: str
    warnings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    related_knowledge: list[str] = field(default_factory=list)
    raw_response: str = ""

    def to_dict(self) -> dict:
        return {
            "task": self.task.value,
            "description": self.description,
            "confidence": self.confidence,
            "warnings": self.warnings,
            "recommendations": self.recommendations,
            "related_knowledge": self.related_knowledge,
        }


VISION_PROMPTS = {
    VisionTask.PLANT_IDENTIFY: (
        "You are a survival botanist. Analyze this image of a plant.\n"
        "Respond in JSON format:\n"
        '{"identification": "plant name or unknown", "edible": true/false, '
        '"toxic": true/false, "confidence": "high/medium/low", '
        '"preparation": "how to prepare if edible", '
        '"warnings": ["warning1", "warning2"], '
        '"lookalikes": "dangerous plants that look similar"}\n'
        "If you cannot identify the plant, say so clearly. Never guess about edibility."
    ),
    VisionTask.WOUND_ASSESS: (
        "You are a wilderness medical assistant. Analyze this image of a wound or injury.\n"
        "Respond in JSON format:\n"
        '{"type": "wound type", "severity": "minor/moderate/severe/critical", '
        '"infection_risk": "low/medium/high", "treatment": "immediate treatment steps", '
        '"warnings": ["warning1"], "needs_professional": true/false}\n'
        "Always recommend seeking professional medical help when possible."
    ),
    VisionTask.HAZARD_DETECT: (
        "You are a survival hazard analyst. Analyze this image for potential dangers.\n"
        "Respond in JSON format:\n"
        '{"hazards": ["hazard1", "hazard2"], "risk_level": "low/medium/high/critical", '
        '"avoidance": "how to avoid", "immediate_action": "what to do right now"}\n'
        "Prioritize immediate threats to life."
    ),
    VisionTask.SHELTER_EVAL: (
        "You are a survival shelter evaluator. Analyze this image of a shelter or potential shelter location.\n"
        "Respond in JSON format:\n"
        '{"type": "shelter type", "condition": "poor/fair/good/excellent", '
        '"weather_protection": "low/medium/high", "improvements": ["improvement1"], '
        '"capacity": "estimated number of people", "hazards": ["hazard1"]}'
    ),
    VisionTask.WATER_SOURCE: (
        "You are a survival water specialist. Analyze this image of a water source.\n"
        "Respond in JSON format:\n"
        '{"type": "water source type", "clarity": "clear/cloudy/muddy", '
        '"likely_safe": true/false, "treatment_needed": "treatment method", '
        '"flow_rate": "still/slow/moderate/fast", "warnings": ["warning1"]}\n'
        "Always assume water is unsafe until treated."
    ),
    VisionTask.TOOL_IDENTIFY: (
        "You are a survival tool expert. Analyze this image of a tool or object.\n"
        "Respond in JSON format:\n"
        '{"tool": "tool name or unknown", "useful_for": ["use1", "use2"], '
        '"condition": "broken/worn/functional/good", "survival_uses": ["use1"], '
        '"hazards": ["hazard1"]}'
    ),
    VisionTask.GENERAL: (
        "You are AllSpark (火种), an offline AI survival system. Analyze this image from a survival perspective.\n"
        "Respond in JSON format:\n"
        '{"description": "what you see", "survival_relevance": "high/medium/low", '
        '"resources": ["resource1"], "threats": ["threat1"], '
        '"recommendations": ["rec1"], "warnings": ["warn1"]}'
    ),
}


class VisionEngine:
    def __init__(self, llm_engine=None, db=None, local_vision=None):
        self.llm = llm_engine
        self.db = db
        self.local_vision = local_vision
        self._available = False
        self._multimodal = False
        self._check_availability()

    def _check_availability(self):
        if self.local_vision and self.local_vision.is_available():
            self._available = True
        if not self.llm or not self.llm.available:
            return

        try:
            llm = self.llm._llm
            if hasattr(llm, 'create_chat_completion'):
                self._available = True
                self._multimodal = self._check_multimodal()
        except Exception:
            self._available = False

    def _check_multimodal(self) -> bool:
        try:
            status = self.llm.get_status() or {}
            model_path = status.get("model_path") or ""
            multimodal_keywords = ["vl", "vision", "visual", "mm", "qwen2-vl", "llava", "bakllava", "cogvlm"]
            return any(kw in model_path.lower() for kw in multimodal_keywords)
        except Exception:
            return False

    @property
    def available(self) -> bool:
        return self._available

    @property
    def is_multimodal(self) -> bool:
        return self._multimodal

    def analyze_image(self, image_path: str, task: VisionTask = VisionTask.GENERAL,
                      custom_prompt: str = "") -> VisionResult:
        if not self._available:
            return VisionResult(
                task=task,
                description="Vision engine not available. LLM is not loaded.",
                confidence="none",
                warnings=["Vision requires a loaded LLM model"],
            )

        path = Path(image_path)
        if not path.exists():
            return VisionResult(
                task=task,
                description=f"Image file not found: {image_path}",
                confidence="none",
            )

        prompt = custom_prompt or VISION_PROMPTS.get(task, VISION_PROMPTS[VisionTask.GENERAL])

        if self._multimodal:
            return self._analyze_multimodal(path, prompt, task)
        if self.local_vision and self.local_vision.is_available():
            return self._analyze_local(path, task)
        return self._analyze_text_only(path, prompt, task)

    def _analyze_multimodal(self, image_path: Path, prompt: str, task: VisionTask) -> VisionResult:
        try:
            import base64
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")

            ext = image_path.suffix.lower()
            mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                        ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}
            mime_type = mime_map.get(ext, "image/jpeg")

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_data}"}},
                    ],
                },
            ]

            response = self.llm.chat(messages, max_tokens=512, temperature=0.3)
            return self._parse_response(response, task)

        except Exception as e:
            return VisionResult(
                task=task,
                description=f"Multimodal analysis failed: {e}",
                confidence="none",
            )

    def _analyze_local(self, image_path: Path, task: VisionTask) -> VisionResult:
        if task == VisionTask.PLANT_IDENTIFY:
            return self.local_vision.assess_plant_safety(str(image_path))
        return self.local_vision.detect_survival_objects(str(image_path))

    def _analyze_text_only(self, image_path: Path, prompt: str, task: VisionTask) -> VisionResult:
        high_risk_tasks = {
            VisionTask.PLANT_IDENTIFY,
            VisionTask.WOUND_ASSESS,
            VisionTask.HAZARD_DETECT,
            VisionTask.WATER_SOURCE,
        }
        if task in high_risk_tasks:
            return VisionResult(
                task=task,
                description="Vision model unavailable for safety-critical image analysis.",
                confidence="none",
                warnings=["Do not rely on metadata-only analysis for plants, wounds, hazards, or water safety."],
                recommendations=["Use a real multimodal/local vision model or seek expert verification."],
            )

        file_info = self._get_image_metadata(image_path)

        text_prompt = (
            f"{prompt}\n\n"
            f"Note: You cannot directly see this image. Here is the file metadata:\n"
            f"- Filename: {image_path.name}\n"
            f"- Size: {file_info['size_kb']:.1f} KB\n"
            f"- Format: {file_info['format']}\n"
            f"- Dimensions: {file_info.get('dimensions', 'unknown')}\n\n"
            f"Based on the filename and metadata, provide your best assessment. "
            f"Clearly state that you cannot actually see the image."
        )

        response = self.llm.survival_chat(text_prompt, context=f"Image analysis task: {task.value}")
        result = self._parse_response(response, task)
        result.confidence = "low"
        result.warnings.insert(0, "Analysis based on metadata only (no multimodal model loaded)")
        return result

    def _get_image_metadata(self, path: Path) -> dict:
        stat = path.stat()
        ext = path.suffix.lower()
        format_map = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG",
                      ".gif": "GIF", ".webp": "WebP", ".bmp": "BMP"}

        info = {
            "size_kb": stat.st_size / 1024,
            "format": format_map.get(ext, "Unknown"),
        }

        try:
            from PIL import Image
            with Image.open(path) as img:
                info["dimensions"] = f"{img.width}x{img.height}"
                info["mode"] = img.mode
        except ImportError:
            pass
        except Exception:
            pass

        return info

    def _parse_response(self, response: str, task: VisionTask) -> VisionResult:
        if not response:
            return VisionResult(task=task, description="No response from LLM", confidence="none")

        try:
            json_str = response
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0]
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0]

            data = json.loads(json_str.strip())

            description = data.get("description", data.get("identification", data.get("type", "")))
            confidence = data.get("confidence", data.get("risk_level", "unknown"))
            warnings = data.get("warnings", data.get("hazards", []))
            if isinstance(warnings, str):
                warnings = [warnings]

            recommendations = data.get("recommendations", data.get("treatment", data.get("improvements", [])))
            if isinstance(recommendations, str):
                recommendations = [recommendations]

            related = []
            if self.db:
                search_terms = []
                if description:
                    search_terms.append(description)
                if isinstance(warnings, list) and warnings:
                    search_terms.append(str(warnings[0]))
                for term in search_terms[:2]:
                    results = self.db.search_knowledge(term, limit=2)
                    for r in results:
                        if r.id not in related:
                            related.append(r.id)

            return VisionResult(
                task=task,
                description=str(description),
                confidence=str(confidence),
                warnings=[str(w) for w in warnings],
                recommendations=[str(r) for r in recommendations],
                related_knowledge=related,
                raw_response=response,
            )
        except (json.JSONDecodeError, KeyError, IndexError):
            return VisionResult(
                task=task,
                description=response[:500],
                confidence="unknown",
                raw_response=response,
            )

    def get_status(self) -> dict:
        return {
            "available": self._available,
            "multimodal": self._multimodal,
            "llm_model": self.llm.model_name if self.llm else None,
            "supported_tasks": [t.value for t in VisionTask],
        }
