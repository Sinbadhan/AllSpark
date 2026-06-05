"""LocalVisionEngine — lightweight local image recognition fallback.

PRD: local image recognition model independent from multimodal LLM.
Uses ONNX Runtime when a local model is available; otherwise degrades safely.
"""

import logging
from pathlib import Path

from allspark.base_service import BaseService
from allspark.core.config import DEFAULT_DB_DIR
from allspark.core.database import Database
from allspark.services.vision_engine import VisionResult, VisionTask

logger = logging.getLogger(__name__)

_SURVIVAL_LABEL_MAP = {
    "bottle": "water_container",
    "water": "water_source",
    "stream": "water_source",
    "river": "water_source",
    "mushroom": "plant_or_fungus",
    "plant": "plant_or_fungus",
    "knife": "tool",
    "axe": "tool",
    "hammer": "tool",
    "fire": "hazard",
    "smoke": "hazard",
    "snake": "hazard",
    "dog": "wildlife",
    "tent": "shelter",
}


class LocalVisionEngine(BaseService):
    SERVICE_NAME = "local_vision"

    def __init__(self, db: Database = None, **kwargs):
        super().__init__(db, **kwargs)
        self.model_dir = Path(kwargs.get("model_dir") or DEFAULT_DB_DIR / "models" / "vision")
        self.model_path = Path(kwargs.get("model_path")) if kwargs.get("model_path") else None
        self._session = None
        self._available = False
        self._fallback_labels = kwargs.get("fallback_labels", False)

    def startup(self) -> None:
        if self._fallback_labels:
            self._available = True
            return
        try:
            import onnxruntime as ort
            model_path = self.model_path or self._find_model()
            if not model_path:
                self._available = False
                return
            self._session = ort.InferenceSession(str(model_path))
            self._available = True
        except Exception as e:
            logger.info("LocalVisionEngine unavailable: %s", e)
            self._available = False

    def is_available(self) -> bool:
        return self._available

    def classify(self, image_path: str, top_k: int = 5) -> list[dict]:
        """Classify image and return labels with confidence.

        In fallback_labels mode, labels are inferred from filename for testing and
        graceful low-end behavior.
        """
        path = Path(image_path)
        if not path.exists():
            return []
        if self._fallback_labels:
            return self._classify_from_filename(path, top_k)
        if not self._session:
            return []
        # Placeholder for ONNX preprocessing/inference. Kept conservative so
        # absence of model/deps never breaks the system.
        return []

    def detect_survival_objects(self, image_path: str) -> VisionResult:
        labels = self.classify(image_path, top_k=5)
        categories = []
        for item in labels:
            label = item.get("label", "").lower()
            for key, category in _SURVIVAL_LABEL_MAP.items():
                if key in label and category not in categories:
                    categories.append(category)
        desc = ", ".join(categories) if categories else "No survival-relevant object detected"
        return VisionResult(
            task=VisionTask.GENERAL,
            description=desc,
            confidence="medium" if categories else "low",
            recommendations=[f"Detected: {c}" for c in categories],
            raw_response=str(labels),
        )

    def assess_plant_safety(self, image_path: str) -> VisionResult:
        labels = self.classify(image_path, top_k=5)
        plant_like = any(
            any(word in item.get("label", "").lower() for word in ["plant", "mushroom", "berry", "leaf"])
            for item in labels
        )
        if not plant_like:
            return VisionResult(
                task=VisionTask.PLANT_IDENTIFY,
                description="No plant-like object detected",
                confidence="low",
                warnings=["Local model cannot confirm edibility"],
            )
        return VisionResult(
            task=VisionTask.PLANT_IDENTIFY,
            description="Plant-like object detected",
            confidence="low",
            warnings=["Never eat wild plants based only on image recognition"],
            recommendations=["Cross-check with plant safety database and local knowledge"],
            raw_response=str(labels),
        )

    def _find_model(self) -> Path | None:
        if not self.model_dir.exists():
            return None
        for name in ["mobilenetv3.onnx", "efficientnet_lite.onnx", "vision.onnx"]:
            path = self.model_dir / name
            if path.exists():
                return path
        return None

    def _classify_from_filename(self, path: Path, top_k: int) -> list[dict]:
        stem = path.stem.lower().replace("_", " ").replace("-", " ")
        labels = []
        for key in _SURVIVAL_LABEL_MAP:
            if key in stem:
                labels.append({"label": key, "confidence": 0.8})
        if not labels:
            labels.append({"label": "unknown", "confidence": 0.1})
        return labels[:top_k]
