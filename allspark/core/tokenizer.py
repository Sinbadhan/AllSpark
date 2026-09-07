import re
from functools import lru_cache
from types import ModuleType


@lru_cache(maxsize=1)
def _get_jieba() -> ModuleType | None:
    """Load the optional dictionary only when non-empty text needs indexing.

    Configuration, help and metadata imports do not need segmentation. Actual
    indexing uses the same upstream model data; a missing dependency retains
    the simple fallback. No tracing or coverage configuration is changed.
    """
    from allspark.core._jieba_data import discard_model, prime_model

    model = prime_model()
    try:
        # A normal import also keeps the optional dependency discoverable by
        # PyInstaller; dynamic import strings would require a separate hook.
        import jieba
        return jieba
    except ImportError:
        discard_model(model)
        return None


def tokenize(text: str) -> str:
    if not text:
        return ""
    jieba = _get_jieba()
    if jieba is not None:
        words = jieba.cut_for_search(text)
        tokens = [w.strip() for w in words if w.strip()]
        return " ".join(tokens)
    return _simple_tokenize(text)


def _simple_tokenize(text: str) -> str:
    parts = re.findall(r'[a-zA-Z]+|\d+|[\u4e00-\u9fff]', text)
    return " ".join(parts)


def tokenize_query(query: str) -> str:
    if not query:
        return ""
    jieba = _get_jieba()
    if jieba is not None:
        words = jieba.cut_for_search(query)
        tokens = [w.strip() for w in words if w.strip()]
    else:
        tokens = query.split()
    safe_tokens = [
        token
        for token in tokens
        if re.search(r"[a-zA-Z0-9\u4e00-\u9fff]", token)
    ]
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in safe_tokens)
