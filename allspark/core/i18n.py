import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

SUPPORTED_LANGUAGES = ["zh", "en"]
DEFAULT_LANGUAGE = "zh"
_current_lang = DEFAULT_LANGUAGE
_db_ref = None

_LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"

# Loaded messages cache
MESSAGES: dict[str, dict[str, str]] = {}


def _load_locale(lang: str) -> dict[str, str]:
    """Load locale messages from YAML file."""
    path = _LOCALES_DIR / f"{lang}.yaml"
    if not path.exists():
        logger.warning("Locale file not found: %s", path)
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.error("Failed to load locale %s: %s", lang, e)
        return {}


def _ensure_loaded():
    """Ensure both locales are loaded."""
    for lang in SUPPORTED_LANGUAGES:
        if lang not in MESSAGES:
            MESSAGES[lang] = _load_locale(lang)


# Load locales on module import
_ensure_loaded()


def set_language(lang: str, persist: bool = True):
    global _current_lang
    if lang in SUPPORTED_LANGUAGES:
        _current_lang = lang
        if persist and _db_ref is not None:
            try:
                _db_ref.conn.execute(
                    "INSERT OR REPLACE INTO operating_state VALUES (?,?)",
                    ("language", lang)
                )
                _db_ref.conn.commit()
            except Exception:
                pass


def get_language() -> str:
    return _current_lang


def init_language(db=None):
    global _current_lang, _db_ref
    _db_ref = db
    if db is not None:
        try:
            row = db.conn.execute(
                "SELECT value FROM operating_state WHERE key='language'"
            ).fetchone()
            if row is not None and row["value"] in SUPPORTED_LANGUAGES:
                _current_lang = row["value"]
        except Exception:
            pass


def detect_language(text: str) -> str:
    zh_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    en_chars = sum(1 for c in text if c.isascii() and c.isalpha())
    if zh_chars > en_chars:
        return "zh"
    elif en_chars > zh_chars:
        return "en"
    return _current_lang


def t(key: str, **kwargs) -> str:
    lang = get_language()
    msg = MESSAGES.get(lang, MESSAGES.get(DEFAULT_LANGUAGE, {})).get(key, key)
    if kwargs:
        try:
            return msg.format(**kwargs)
        except (KeyError, IndexError):
            return msg
    return msg
