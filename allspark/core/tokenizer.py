import re

try:
    import jieba
    JIEBA_AVAILABLE = True
except ImportError:
    JIEBA_AVAILABLE = False


def tokenize(text: str) -> str:
    if not text:
        return ""
    if JIEBA_AVAILABLE:
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
    if JIEBA_AVAILABLE:
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
