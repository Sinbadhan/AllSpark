from pathlib import Path
from allspark.models import OperatingMode

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

PERSONALITY_TEMPLATES = {
    "crisis": {
        "greeting": "⚠️ 紧急状态",
        "style": "directive",
        "emoji_prefix": "🚨",
        "verbosity": "minimal",
        "tone": "urgent",
    },
    "stable": {
        "greeting": "状态正常",
        "style": "informative",
        "emoji_prefix": "✅",
        "verbosity": "normal",
        "tone": "calm",
    },
    "companion": {
        "greeting": "我在这里",
        "style": "conversational",
        "emoji_prefix": "🔥",
        "verbosity": "detailed",
        "tone": "warm",
    },
    "multiplayer": {
        "greeting": "多人协作中",
        "style": "neutral",
        "emoji_prefix": "👥",
        "verbosity": "normal",
        "tone": "authoritative",
    },
    "renaissance": {
        "greeting": "文明在生长",
        "style": "educational",
        "emoji_prefix": "🟣",
        "verbosity": "detailed",
        "tone": "inspiring",
    },
}

INTENT_KEYWORDS = {
    "water": ["水", "渴", "喝水", "净水", "水源", "找水", "饮水", "water", "thirst"],
    "fire": ["火", "生火", "点火", "取暖", "取暖", "燃烧", "fire", "warm", "点燃"],
    "food": ["食物", "吃", "饿", "觅食", "可食用", "有毒", "植物", "狩猎", "捕鱼", "food", "hunger", "hungry"],
    "shelter": ["庇护所", "住", "帐篷", "避难", "遮蔽", "房屋", "shelter", "camp"],
    "medical": ["伤", "血", "急救", "病", "疼痛", "发烧", "感染", "CPR", "止血", "medical", "hurt", "injury"],
    "navigation": ["方向", "导航", "指南针", "地图", "星", "位置", "navigation", "compass", "map"],
    "resource": ["资源", "物资", "储备", "存量", "resource"],
    "status": ["状态", "情况", "怎么样", "汇报", "status"],
    "help": ["帮助", "怎么用", "你能做什么", "help"],
}

PHASE_DESCRIPTIONS = {
    0: "立即生存 (0-72h)",
    1: "短期生存 (1-30天)",
    2: "中期自给 (1-12月)",
    3: "生活质量 (1-5年)",
    4: "文明复兴 (5年+)",
}

PHASE_GOALS = {
    0: ["止血和急救", "寻找水源", "搭建临时庇护所", "评估环境威胁"],
    1: ["稳定食物供应", "确保饮用水安全", "建立安全庇护所", "获取火源"],
    2: ["开始农业种植", "制造基本工具", "建立能源供给", "改善居住条件"],
    3: ["建立医疗能力", "建立通信手段", "提高生活舒适度", "积累知识储备"],
    4: ["传承教育体系", "发展科学技术", "建立社区治理", "记录文明历史"],
}

SPARKNET_DISCOVERY_PORT = 7979
SPARKNET_EXCHANGE_PORT = 7980
SPARKNET_BEACON_INTERVAL = 30
SPARKNET_DISCOVERY_TIMEOUT = 10
SPARKNET_MESSAGE_ENCODING = "utf-8"
SPARKNET_BUFFER_SIZE = 4096
