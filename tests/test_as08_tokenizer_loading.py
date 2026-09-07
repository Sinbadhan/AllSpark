"""Optional dictionary loading must not penalize unrelated entrypoints."""
import builtins
import subprocess
import sys

import pytest

from allspark.core import tokenizer


def test_dictionary_loads_on_first_real_query_not_package_import():
    result = subprocess.run(
        [sys.executable, "-c", """
import sys
from allspark.core.tokenizer import tokenize, tokenize_query
assert 'jieba' not in sys.modules
assert tokenize('') == ''
assert tokenize_query('') == ''
assert 'jieba' not in sys.modules
assert tokenize('安全饮水 water') == '安全 饮水 water'
assert tokenize_query('安全饮水 water') == '"安全" OR "饮水" OR "water"'
assert 'jieba' in sys.modules
"""], capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("function,text,expected", [
    ("tokenize", "饮水 water 123!", "饮 水 water 123"),
    ("tokenize_query", 'water " OR *', '"water" OR "OR"'),
])
def test_missing_dictionary_preserves_safe_fallback(monkeypatch, function, text, expected):
    calls = []
    original_import = builtins.__import__

    def unavailable(name, *args, **kwargs):
        if name == "jieba":
            calls.append(name)
            raise ImportError(name)
        return original_import(name, *args, **kwargs)

    tokenizer._get_jieba.cache_clear()
    monkeypatch.setattr(builtins, "__import__", unavailable)
    try:
        assert getattr(tokenizer, function)(text) == expected
        assert getattr(tokenizer, function)(text) == expected
        assert calls == ["jieba"]
    finally:
        tokenizer._get_jieba.cache_clear()
