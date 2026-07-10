"""Tests for LocalVisionEngine — local image recognition fallback."""

import pytest

from allspark.core.database import Database
from allspark.services.local_vision import LocalVisionEngine
from allspark.services.vision_engine import VisionEngine, VisionTask


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "test.db"))


def make_file(tmp_path, name="water_bottle.jpg"):
    p = tmp_path / name
    p.write_bytes(b"fake-image")
    return p


class TestLocalVisionEngine:
    def test_unavailable_without_model(self, db, tmp_path):
        lv = LocalVisionEngine(db, model_dir=tmp_path)
        lv.startup()
        assert lv.is_available() is False

    def test_fallback_labels_available(self, db):
        lv = LocalVisionEngine(db, fallback_labels=True)
        lv.startup()
        assert lv.is_available() is True

    def test_classify_from_filename(self, db, tmp_path):
        img = make_file(tmp_path, "water_bottle.jpg")
        lv = LocalVisionEngine(db, fallback_labels=True)
        lv.startup()
        labels = lv.classify(str(img))
        assert any("water" in item["label"] or "bottle" in item["label"] for item in labels)

    def test_detect_survival_objects(self, db, tmp_path):
        img = make_file(tmp_path, "knife_tool.jpg")
        lv = LocalVisionEngine(db, fallback_labels=True)
        lv.startup()
        result = lv.detect_survival_objects(str(img))
        assert "tool" in result.description

    def test_assess_plant_safety(self, db, tmp_path):
        img = make_file(tmp_path, "mushroom.jpg")
        lv = LocalVisionEngine(db, fallback_labels=True)
        lv.startup()
        result = lv.assess_plant_safety(str(img))
        assert result.task == VisionTask.PLANT_IDENTIFY
        assert result.warnings

    def test_missing_file_returns_empty(self, db, tmp_path):
        lv = LocalVisionEngine(db, fallback_labels=True)
        lv.startup()
        assert lv.classify(str(tmp_path / "missing.jpg")) == []


class TestVisionEngineIntegration:
    def test_vision_uses_local_fallback_without_llm(self, db, tmp_path):
        img = make_file(tmp_path, "water_source.jpg")
        lv = LocalVisionEngine(db, fallback_labels=True)
        lv.startup()
        ve = VisionEngine(llm_engine=None, db=db, local_vision=lv)
        result = ve.analyze_image(str(img), VisionTask.GENERAL)
        assert "water_source" in result.description

    def test_vision_plant_task_uses_local(self, db, tmp_path):
        img = make_file(tmp_path, "plant_leaf.jpg")
        lv = LocalVisionEngine(db, fallback_labels=True)
        lv.startup()
        ve = VisionEngine(llm_engine=None, db=db, local_vision=lv)
        result = ve.analyze_image(str(img), VisionTask.PLANT_IDENTIFY)
        assert result.task == VisionTask.PLANT_IDENTIFY
