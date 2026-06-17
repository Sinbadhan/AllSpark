"""LLM model registry — single source of truth for tier→model mapping
and download URLs.

Loads ``allspark/data/models.yaml`` and exposes:

  - ``get_recommended_model(tier)``  default model for a hardware tier
  - ``get_model(name)``               full entry by id
  - ``list_models(role=None)``        catalog browse (filter by role)
  - ``resolve_model_name(tier)``      tier default, with override priority:
        1. ``ALLSPARK_LLM_MODEL`` env var
        2. ``~/.allspark/config.toml`` ``[llm] model = "..."``
        3. ``recommendations[tier]`` from yaml
  - ``ModelEntry``                    typed view over a yaml entry

Replaces three pre-v1.0.2 hardcoded dicts:
  * ``infrastructure/hardware.py:LLM_MODEL_MAP``
  * ``adapters/web_ui.py:MODEL_DOWNLOAD_URLS / MIRROR_DOWNLOAD_URLS``
  * ``adapters/init_wizard.py:MODEL_DOWNLOAD_URLS / MIRROR_URLS``
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

from allspark.core.config import DEFAULT_DB_DIR
from allspark.infrastructure.hardware import HardwareTier

logger = logging.getLogger(__name__)

_MODELS_YAML = Path(__file__).resolve().parent.parent / "data" / "models.yaml"
_CONFIG_TOML = DEFAULT_DB_DIR / "config.toml"
_ENV_OVERRIDE = "ALLSPARK_LLM_MODEL"

# Cached registry. Cleared by ``reload()`` and on import-time errors.
_cache: dict[str, Any] | None = None


@dataclass(frozen=True)
class ModelEntry:
    """Typed view of a single model entry from the yaml."""

    name: str
    family: str
    role: str
    quant: str
    file_gb: float
    runtime_gb: float
    min_ram_gb: int
    speed_tps: str
    context: int
    notes: str
    url_hf: str
    url_mirror: str = ""

    @property
    def primary_url(self) -> str:
        """Mirror first if defined (faster in regions with limited HF
        access), otherwise HuggingFace."""
        return self.url_mirror or self.url_hf

    def to_legacy_dict(self) -> dict[str, Any]:
        """Shape compatible with the old LLM_MODEL_MAP entries.

        Old code expected ``{"model": str, "size_gb": float, "speed_tps":
        str}``. Kept as a shim until callers migrate.
        """
        return {
            "model": self.name,
            "size_gb": self.file_gb,
            "speed_tps": self.speed_tps,
        }


def _load_yaml() -> dict[str, Any]:
    if not _MODELS_YAML.exists():
        raise FileNotFoundError(f"models.yaml missing: {_MODELS_YAML}")
    with _MODELS_YAML.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError(f"models.yaml schema unsupported (expect version: 1): {_MODELS_YAML}")
    if "recommendations" not in data or "models" not in data:
        raise ValueError("models.yaml must define `recommendations:` and `models:` keys")
    return data


def _load() -> dict[str, Any]:
    global _cache
    if _cache is None:
        _cache = _load_yaml()
    return _cache


def reload() -> None:
    """Drop the in-memory cache. Tests call this between fixtures; live
    code shouldn't need it."""
    global _cache
    _cache = None


def _entry(data: dict[str, Any], name: str) -> ModelEntry:
    raw = data["models"].get(name)
    if raw is None:
        raise KeyError(f"model '{name}' not in models.yaml `models:`")
    return ModelEntry(
        name=name,
        family=raw["family"],
        role=raw.get("role", "general"),
        quant=raw.get("quant", "Q4_K_M"),
        file_gb=float(raw["file_gb"]),
        runtime_gb=float(raw["runtime_gb"]),
        min_ram_gb=int(raw["min_ram_gb"]),
        speed_tps=str(raw.get("speed_tps", "")),
        context=int(raw.get("context", 0)),
        notes=str(raw.get("notes", "")).strip(),
        url_hf=str(raw["url_hf"]),
        url_mirror=str(raw.get("url_mirror", "")),
    )


def get_model(name: str) -> ModelEntry:
    """Full catalog entry by id. Raises KeyError on miss."""
    return _entry(_load(), name)


def get_recommended_model(tier: HardwareTier | str) -> ModelEntry:
    """Default model for a hardware tier (no overrides applied)."""
    data = _load()
    key = tier.name if isinstance(tier, HardwareTier) else str(tier)
    rec = data["recommendations"].get(key)
    if rec is None:
        raise KeyError(f"no recommendation for tier '{key}'")
    return _entry(data, rec)


def list_models(role: Optional[str] = None) -> list[ModelEntry]:
    """All catalog entries, optionally filtered by role
    (general/reasoning/coder/...)."""
    data = _load()
    out: list[ModelEntry] = []
    for name in data["models"]:
        e = _entry(data, name)
        if role is None or e.role == role:
            out.append(e)
    return out


def _read_config_toml() -> Optional[str]:
    """Return the value of [llm].model from ~/.allspark/config.toml,
    or None if missing/unreadable."""
    if not _CONFIG_TOML.exists():
        return None
    try:
        with _CONFIG_TOML.open("rb") as f:
            cfg = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.warning("config.toml unreadable, ignoring: %s", exc)
        return None
    section = cfg.get("llm") or {}
    name = section.get("model")
    return str(name) if isinstance(name, str) and name else None


def resolve_model_name(tier: HardwareTier | str) -> str:
    """Pick the model for ``tier``, applying the override chain:

    1. ``ALLSPARK_LLM_MODEL`` env var (if set and non-empty)
    2. ``~/.allspark/config.toml`` ``[llm] model``
    3. ``recommendations[tier]`` from yaml

    Override values that don't match any catalog entry are accepted as-is
    (callers may want to load an arbitrary local .gguf by name) — we just
    log a warning so misuse is visible.
    """
    env = os.environ.get(_ENV_OVERRIDE, "").strip()
    if env:
        if env not in _load()["models"]:
            logger.warning(
                "ALLSPARK_LLM_MODEL=%s not in catalog; using as raw name", env
            )
        return env

    cfg = _read_config_toml()
    if cfg:
        if cfg not in _load()["models"]:
            logger.warning(
                "config.toml [llm].model=%s not in catalog; using as raw name", cfg
            )
        return cfg

    return get_recommended_model(tier).name


def get_download_urls(name: str) -> tuple[str, str]:
    """Return (mirror_url, hf_url) for ``name``. Mirror may be empty
    string when the model has no mirror entry."""
    e = get_model(name)
    return e.url_mirror, e.url_hf
