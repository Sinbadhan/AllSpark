"""Load Jieba's own probability data without executing its huge dict literal.

The 0.42.1 distribution includes equivalent Python and pickle encodings. CPython
3.12 tracing makes the former expensive even outside coverage's source scope.
Only the known data hash is eligible; other distributions keep Jieba's ordinary
import path. This module never changes a tracer or an installed file.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import pickle
import sys
from pathlib import Path
from types import ModuleType

_MODEL_NAME = "jieba.finalseg.prob_emit"
_MODEL_SHA256 = "1e1d1d835b0c77d234acaa6afa23a13ffce597a295be0d7a1ece6a0d440dcf08"


class _DataOnlyUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str):
        raise pickle.UnpicklingError("Jieba probability model must contain data only")


def prime_model() -> ModuleType | None:
    """Return a newly installed data module, or leave upstream loading intact."""
    if _MODEL_NAME in sys.modules:
        return None
    spec = importlib.util.find_spec("jieba")
    if spec is None or spec.origin is None:
        return None
    # Wheels and the existing PyInstaller data hook retain this layout.
    # Zip/custom loaders or newer data versions use the original module.
    path = Path(spec.origin).parent / "finalseg" / "prob_emit.p"
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if hashlib.sha256(raw).hexdigest() != _MODEL_SHA256:
        return None
    model = ModuleType(_MODEL_NAME)
    model.__file__ = str(path)
    model.__package__ = "jieba.finalseg"
    setattr(model, "P", _DataOnlyUnpickler(io.BytesIO(raw)).load())
    return model if sys.modules.setdefault(_MODEL_NAME, model) is model else None


def discard_model(model: ModuleType | None) -> None:
    """Undo only our own insertion if importing the optional package failed."""
    if model is not None and sys.modules.get(_MODEL_NAME) is model:
        del sys.modules[_MODEL_NAME]
