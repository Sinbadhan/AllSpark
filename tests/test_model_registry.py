"""Tests for allspark.services.model_registry."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from allspark.infrastructure.hardware import HardwareTier
from allspark.services import model_registry as mr


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset registry cache between tests so env/config patches take effect."""
    mr.reload()
    yield
    mr.reload()


def test_recommendations_cover_every_tier():
    """Every HardwareTier must have a recommended model in the catalog."""
    for tier in HardwareTier:
        entry = mr.get_recommended_model(tier)
        assert entry.name
        assert entry.url_hf  # must have at least primary URL


def test_recommendations_fit_their_tier():
    """A tier's recommended model must not require more RAM than the
    tier's threshold (otherwise users would auto-OOM)."""
    from allspark.infrastructure.hardware import TIER_THRESHOLDS

    for tier in HardwareTier:
        entry = mr.get_recommended_model(tier)
        ram_threshold = TIER_THRESHOLDS[tier]["ram_gb"]
        if tier == HardwareTier.PHANTOM:
            # Phantom is the bottom — its threshold is 0 (any device).
            # Recommended model just needs to be tiny.
            assert entry.runtime_gb < 2
        else:
            assert entry.min_ram_gb <= ram_threshold, (
                f"{tier.name} recommended {entry.name} needs "
                f"{entry.min_ram_gb}GB but tier threshold is {ram_threshold}GB"
            )


def test_get_model_unknown_raises_keyerror():
    with pytest.raises(KeyError):
        mr.get_model("not-a-real-model")


def test_get_recommended_model_accepts_string_or_enum():
    e1 = mr.get_recommended_model(HardwareTier.MINIMUM)
    e2 = mr.get_recommended_model("MINIMUM")
    assert e1.name == e2.name


def test_list_models_filters_by_role():
    general = mr.list_models(role="general")
    reasoning = mr.list_models(role="reasoning")
    assert all(e.role == "general" for e in general)
    assert all(e.role == "reasoning" for e in reasoning)
    assert len(general) >= 1
    assert len(reasoning) >= 1


def test_list_models_no_filter_returns_full_catalog():
    everyone = mr.list_models()
    assert len(everyone) >= len(mr.list_models(role="general"))


def test_v4_flash_in_catalog_but_not_a_recommendation():
    """V4-Flash must be reachable for users who want to opt in, but it
    must NOT be the default for any current tier (it needs ≥192 GB)."""
    flash = mr.get_model("deepseek-v4-flash")
    assert flash.min_ram_gb >= 192
    for tier in HardwareTier:
        rec = mr.get_recommended_model(tier)
        assert rec.name != "deepseek-v4-flash"


def test_v4_pro_in_catalog_but_not_a_recommendation():
    pro = mr.get_model("deepseek-v4-pro")
    assert pro.min_ram_gb >= 1024
    for tier in HardwareTier:
        rec = mr.get_recommended_model(tier)
        assert rec.name != "deepseek-v4-pro"


def test_resolve_model_default_path():
    name = mr.resolve_model_name(HardwareTier.RECOMMENDED)
    assert name == "qwen3-8b-instruct-q4"


def test_resolve_model_env_override_known():
    with patch.dict(os.environ, {"ALLSPARK_LLM_MODEL": "deepseek-v4-flash"}):
        name = mr.resolve_model_name(HardwareTier.RECOMMENDED)
    assert name == "deepseek-v4-flash"


def test_resolve_model_env_override_unknown_passes_through(caplog: pytest.LogCaptureFixture):
    """Unknown override (e.g. user dropped a custom .gguf) is still used,
    but a warning is logged so misuse is visible."""
    with patch.dict(os.environ, {"ALLSPARK_LLM_MODEL": "my-custom-llama"}):
        with caplog.at_level("WARNING"):
            name = mr.resolve_model_name(HardwareTier.RECOMMENDED)
    assert name == "my-custom-llama"
    assert "not in catalog" in caplog.text


def test_resolve_model_config_toml_override(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[llm]\nmodel = "deepseek-r1-distill-qwen-14b"\n', encoding="utf-8")
    with patch.object(mr, "_CONFIG_TOML", cfg):
        # No env override
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ALLSPARK_LLM_MODEL", None)
            name = mr.resolve_model_name(HardwareTier.COMFORTABLE)
    assert name == "deepseek-r1-distill-qwen-14b"


def test_resolve_model_env_beats_config(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[llm]\nmodel = "deepseek-r1-distill-qwen-14b"\n', encoding="utf-8")
    with patch.object(mr, "_CONFIG_TOML", cfg):
        with patch.dict(os.environ, {"ALLSPARK_LLM_MODEL": "deepseek-v4-flash"}):
            name = mr.resolve_model_name(HardwareTier.COMFORTABLE)
    assert name == "deepseek-v4-flash"


def test_config_toml_corrupt_falls_back_to_default(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("not = valid = toml = [[", encoding="utf-8")  # syntax error
    with patch.object(mr, "_CONFIG_TOML", cfg):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ALLSPARK_LLM_MODEL", None)
            name = mr.resolve_model_name(HardwareTier.MINIMUM)
    assert name == "qwen3-4b-instruct-q4"


def test_legacy_dict_shape():
    e = mr.get_recommended_model(HardwareTier.RECOMMENDED)
    legacy = e.to_legacy_dict()
    assert set(legacy) == {"model", "size_gb", "speed_tps"}
    assert legacy["model"] == e.name


def test_primary_url_prefers_mirror():
    e = mr.get_model("qwen3-8b-instruct-q4")
    assert e.url_mirror  # this entry has a mirror
    assert e.primary_url == e.url_mirror


def test_primary_url_falls_back_to_hf_when_no_mirror():
    e = mr.get_model("deepseek-v4-flash")
    assert e.url_mirror == ""  # this entry has no mirror configured
    assert e.primary_url == e.url_hf
