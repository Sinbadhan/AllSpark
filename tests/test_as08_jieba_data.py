"""Independently verify upstream model equivalence and bounded loader behavior."""
import ast
import hashlib
import importlib.util
import io
import pickle
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from allspark.core import _jieba_data


def test_entire_serialized_model_equals_upstream_python_literal():
    spec = importlib.util.find_spec("jieba")
    assert spec is not None and spec.origin is not None
    root = Path(spec.origin).parent / "finalseg"
    raw = (root / "prob_emit.p").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == _jieba_data._MODEL_SHA256
    parsed = ast.parse((root / "prob_emit.py").read_text(encoding="utf-8"))
    assignment = next(node for node in parsed.body if isinstance(node, ast.Assign))
    assert [t.id for t in assignment.targets] == ["P"]
    literal = ast.literal_eval(assignment.value)
    decoded = _jieba_data._DataOnlyUnpickler(io.BytesIO(raw)).load()
    assert decoded == literal
    assert sorted(decoded) == ["B", "E", "M", "S"]
    assert sum(len(values) for values in decoded.values()) == 35224


@pytest.mark.parametrize("case", ["no_package", "no_origin", "no_file", "new_data"])
def test_unknown_layout_or_data_preserves_original_import(monkeypatch, tmp_path, case):
    monkeypatch.delitem(sys.modules, _jieba_data._MODEL_NAME, raising=False)
    spec = SimpleNamespace(origin=str(tmp_path / "__init__.py"))
    if case == "no_package":
        spec = None
    elif case == "no_origin":
        spec.origin = None
    elif case == "new_data":
        path = tmp_path / "finalseg" / "prob_emit.p"
        path.parent.mkdir()
        path.write_bytes(b"unrecognized upstream data")
    monkeypatch.setattr(_jieba_data.importlib.util, "find_spec", lambda name: spec)
    assert _jieba_data.prime_model() is None
    assert _jieba_data._MODEL_NAME not in sys.modules


def test_existing_module_and_unowned_cleanup_are_preserved(monkeypatch):
    original = ModuleType(_jieba_data._MODEL_NAME)
    monkeypatch.setitem(sys.modules, _jieba_data._MODEL_NAME, original)
    assert _jieba_data.prime_model() is None
    _jieba_data.discard_model(None)
    _jieba_data.discard_model(ModuleType(_jieba_data._MODEL_NAME))
    assert sys.modules[_jieba_data._MODEL_NAME] is original
    _jieba_data.discard_model(original)
    assert _jieba_data._MODEL_NAME not in sys.modules


def test_data_decoder_cannot_resolve_executable_globals():
    with pytest.raises(pickle.UnpicklingError, match="data only"):
        _jieba_data._DataOnlyUnpickler(io.BytesIO(b"cos\nsystem\n.")).load()


def test_failed_optional_import_cleans_up_then_concurrent_real_calls_work():
    result = subprocess.run([sys.executable, "-c", """
import builtins
import sys
from concurrent.futures import ThreadPoolExecutor
from allspark.core import tokenizer
original_import = builtins.__import__
def missing(name, *args, **kwargs):
    if name == 'jieba':
        raise ImportError(name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = missing
assert tokenizer.tokenize('water') == 'water'
assert 'jieba.finalseg.prob_emit' not in sys.modules
builtins.__import__ = original_import
tokenizer._get_jieba.cache_clear()
with ThreadPoolExecutor(max_workers=8) as pool:
    values = list(pool.map(tokenizer.tokenize, ['安全饮水 water'] * 16))
assert values == ['安全 饮水 water'] * 16
assert sys.modules['jieba.finalseg.prob_emit'].__file__.endswith('prob_emit.p')
assert tokenizer.tokenize_query('安全饮水 water') == '"安全" OR "饮水" OR "water"'
"""], text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
