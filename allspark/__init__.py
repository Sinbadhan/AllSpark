__version__ = "1.0.2"
__name_zh__ = "火种"
__name_en__ = "AllSpark"

# Backward-compatible re-exports (Phase D directory restructure)
from allspark.core.config import DEFAULT_DB_DIR, DEFAULT_DB_PATH  # noqa: F401
from allspark.core.database import Database  # noqa: F401
from allspark.core.i18n import detect_language, get_language, init_language, set_language, t  # noqa: F401
from allspark.core.models import *  # noqa: F401,F403
