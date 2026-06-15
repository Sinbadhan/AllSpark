import json
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


# ---------------------------------------------------------------------------
# i18n persistence — store the *key* in DB, render at read time.
# Background: B-2. Storing a translated string in `tasks.title` etc. means
# the user's choice of language at write time gets baked in forever and
# the next `lang xx` switch leaves a half-translated UI behind.
#
# Format: "t:<key>|<json-args>"  (json omitted when args is empty)
#   mark("urgent_find_water")             -> "t:urgent_find_water"
#   mark("timeline_diary", date="2026...")-> 't:timeline_diary|{"date":"2026..."}'
# Anything that doesn't start with "t:" is treated as a literal — that
# preserves user-typed input (manual goal titles, diary content, etc.)
# and stays backward-compatible with rows written before this change.
# ---------------------------------------------------------------------------

_MARKER_PREFIX = "t:"


def mark(key: str, **kwargs) -> str:
    """Encode an i18n key (and optional format args) for DB storage.

    Use anywhere the result will be persisted and later rendered to a
    user-visible string under whatever language is current at read time.
    """
    if kwargs:
        return f"{_MARKER_PREFIX}{key}|{json.dumps(kwargs, ensure_ascii=False, sort_keys=True)}"
    return f"{_MARKER_PREFIX}{key}"


def render(stored: str | None) -> str:
    """Resolve a stored string. Marker → translate. Literal → passthrough.

    Marker args that themselves are markers get resolved recursively, so a
    Goal whose title is `mark("urgent_find_water")` can be safely embedded
    as the `goal_title` arg of another marker — both surface in the same
    language at read time.
    """
    if not stored or not isinstance(stored, str):
        return stored or ""
    if not stored.startswith(_MARKER_PREFIX):
        return stored
    payload = stored[len(_MARKER_PREFIX):]
    if "|" in payload:
        key, raw = payload.split("|", 1)
        try:
            args = json.loads(raw)
        except Exception:
            return t(key)
        if not isinstance(args, dict):
            return t(key)
        # Recursively resolve any nested markers in the args.
        resolved = {k: (render(v) if isinstance(v, str) else v) for k, v in args.items()}
        return t(key, **resolved)
    return t(payload)


def is_marker(stored: str | None) -> bool:
    """True iff `stored` was produced by `mark()`."""
    return isinstance(stored, str) and stored.startswith(_MARKER_PREFIX)
