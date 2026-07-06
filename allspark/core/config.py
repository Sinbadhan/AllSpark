from pathlib import Path

from allspark.core.models import OperatingMode

_LEGACY_DIR = Path.home() / ".spark"
DEFAULT_DB_DIR = Path.home() / ".allspark"

if _LEGACY_DIR.exists() and not DEFAULT_DB_DIR.exists():
    import shutil
    shutil.move(str(_LEGACY_DIR), str(DEFAULT_DB_DIR))

DEFAULT_DB_PATH = DEFAULT_DB_DIR / "data.db"

POWER_MODE_THRESHOLDS = {
    OperatingMode.PROACTIVE: 72,
    OperatingMode.STANDARD: 24,
    OperatingMode.ECONOMY: 6,
    OperatingMode.HIBERNATION: 0,
}

POWER_CONSUMPTION_WATTS = {
    OperatingMode.PROACTIVE: 8,
    OperatingMode.STANDARD: 5,
    OperatingMode.ECONOMY: 3,
    OperatingMode.HIBERNATION: 1,
}

RESOURCE_WARNING_THRESHOLDS = {
    "power": {"warning_hours": 24, "critical_hours": 6},
    "water": {"warning_days": 3, "critical_days": 1},
    "food": {"warning_days": 5, "critical_days": 2},
    "fire": {"warning_uses": 10, "critical_uses": 3},
    "storage": {"warning_percent": 10, "critical_percent": 5},
}

PERSONALITY_GREETING_KEYS = {
    "crisis": "greeting_crisis",
    "stable": "greeting_stable",
    "companion": "greeting_companion",
    "multiplayer": "greeting_multiplayer",
    "renaissance": "greeting_renaissance",
}

PERSONALITY_TEMPLATES = {
    "crisis": {
        "style": "directive",
        "emoji_prefix": "🚨",
        "verbosity": "minimal",
        "tone": "urgent",
    },
    "stable": {
        "style": "informative",
        "emoji_prefix": "✅",
        "verbosity": "normal",
        "tone": "calm",
    },
    "companion": {
        "style": "conversational",
        "emoji_prefix": "🔥",
        "verbosity": "detailed",
        "tone": "warm",
    },
    "multiplayer": {
        "style": "neutral",
        "emoji_prefix": "👥",
        "verbosity": "normal",
        "tone": "authoritative",
    },
    "renaissance": {
        "style": "educational",
        "emoji_prefix": "🟣",
        "verbosity": "detailed",
        "tone": "inspiring",
    },
}

PHASE_DESC_KEYS = {
    0: "phase_desc_0",
    1: "phase_desc_1",
    2: "phase_desc_2",
    3: "phase_desc_3",
    4: "phase_desc_4",
}

PHASE_GOAL_KEYS = {
    0: ["phase_goal_0_0", "phase_goal_0_1", "phase_goal_0_2", "phase_goal_0_3"],
    1: ["phase_goal_1_0", "phase_goal_1_1", "phase_goal_1_2", "phase_goal_1_3"],
    2: ["phase_goal_2_0", "phase_goal_2_1", "phase_goal_2_2", "phase_goal_2_3"],
    3: ["phase_goal_3_0", "phase_goal_3_1", "phase_goal_3_2", "phase_goal_3_3"],
    4: ["phase_goal_4_0", "phase_goal_4_1", "phase_goal_4_2", "phase_goal_4_3"],
}

SPARKNET_DISCOVERY_PORT = 7979
SPARKNET_EXCHANGE_PORT = 7980
SPARKNET_BEACON_INTERVAL = 30
SPARKNET_DISCOVERY_TIMEOUT = 10
SPARKNET_MESSAGE_ENCODING = "utf-8"
SPARKNET_BUFFER_SIZE = 4096
# Cap total bytes accepted on a single TCP exchange connection to prevent
# memory-exhaustion DoS (audit H2). 50 MB is generous for knowledge transfers.
SPARKNET_MAX_INCOMING_BYTES = 50 * 1024 * 1024
