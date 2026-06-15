from dataclasses import dataclass
from typing import Any, Optional

from allspark.infrastructure.hardware import FeatureFlags


@dataclass
class ModuleDef:
    name: str
    description_zh: str
    description_en: str
    feature_flag: str
    is_core: bool = False
    instance: Any = None


MODULE_DEFINITIONS = [
    ModuleDef("rule_engine", "规则引擎 — 确定性生存建议", "Rule Engine — deterministic survival advice", "rule_engine", is_core=True),
    ModuleDef("knowledge_fts", "SQLite 全文检索 — 知识库搜索", "SQLite FTS — knowledge search", "sqlite_fts", is_core=True),
    ModuleDef("knowledge_vector", "向量检索 (RAG) — 语义搜索", "Vector RAG — semantic search", "vector_rag"),
    ModuleDef("kiwix", "Kiwix 维基百科 — 离线百科", "Kiwix Wikipedia — offline encyclopedia", "kiwix"),
    ModuleDef("llm", "本地 LLM — 开放性问答", "Local LLM — open-ended Q&A", "llm"),
    ModuleDef("multilingual", "多语言知识库 — 中英双语", "Multilingual knowledge — zh/en", "multilingual_knowledge"),
    ModuleDef("text_interaction", "纯文字交互 — CLI", "Text interaction — CLI", "text_interaction", is_core=True),
    ModuleDef("image_recognition", "图片识别 — 植物/伤口识别", "Image recognition — plants/wounds", "image_recognition"),
    ModuleDef("voice_input", "语音输入 — Whisper", "Voice input — Whisper", "voice_input"),
    ModuleDef("voice_output", "语音输出 — TTS", "Voice output — TTS", "voice_output"),
    ModuleDef("web_ui", "Web UI — 浏览器界面", "Web UI — browser interface", "web_ui"),
    ModuleDef("offline_map", "离线地图 — 地理信息", "Offline map — geographic info", "offline_map"),
    ModuleDef("kolibri", "可汗学院 (Kolibri) — 教育", "Khan Academy (Kolibri) — education", "kolibri"),
    ModuleDef("spark_network", "火种通信 — 火种间通信", "AllSpark Network — inter-spark comms", "spark_network", is_core=True),
    ModuleDef("skf_manager", "SKF 知识包 — 导入/导出", "SKF Manager — knowledge import/export", "spark_network"),
    ModuleDef("knowledge_verifier", "知识验证 — 来源/一致性/交叉引用", "Knowledge Verifier — source/consistency/cross-ref", "spark_network"),
    ModuleDef("vision_engine", "图像识别 — 多模态分析", "Vision Engine — multimodal analysis", "image_recognition"),
    ModuleDef("multimodal", "多模态交互 — 图文语音融合", "Multimodal — image/text/voice fusion", "multimodal"),
    ModuleDef("self_learning", "自学习沉淀 — 经验积累", "Self-learning — experience accumulation", "self_learning"),
    ModuleDef("governance", "社区治理 — 权限/角色/冲突调解", "Governance — permissions/roles/conflict resolution", "governance"),
    ModuleDef("trade_engine", "知识交易 — 火种间知识交换", "Trade Engine — inter-spark knowledge exchange", "trade_engine"),
    ModuleDef("tier3_knowledge", "Tier 3 知识 — 长期自给/社区重建", "Tier 3 Knowledge — long-term self-sufficiency", "multilingual_knowledge"),
    ModuleDef("power_monitor", "电力监控 — RPi GPIO/模拟", "Power Monitor — RPi GPIO/simulated", "power_monitor"),
    ModuleDef("sensor_hub", "传感器 — 温度/湿度/气压/GPS", "Sensor Hub — temp/humidity/pressure/GPS", "sensor_hub"),
    ModuleDef("data_preservation", "数据固化 — 断电自动保存/快照", "Data Preservation — auto-save/snapshot", "data_preservation"),
    ModuleDef("boot_manager", "启动优化 — systemd/watchdog", "Boot Manager — systemd/watchdog", "boot_manager"),
    ModuleDef("goal_engine", "目标引擎 — 自动生成/里程碑追踪", "Goal Engine — auto-generate/milestone tracking", "self_learning", is_core=True),
    ModuleDef("reset_manager", "重置管理器 — 三级重置/安全约束", "Reset Manager — 3-level reset/safety", "data_preservation"),
    ModuleDef("daily_briefing", "每日简报 — 生存日报", "Daily Briefing — survival report", "self_learning", is_core=True),
    ModuleDef("timeline", "生存时间线 — 事件记录", "Timeline — event recording", "self_learning", is_core=True),
    ModuleDef("diary", "火种日记 — 文字/情绪记录", "Diary — text/emotion recording", "self_learning", is_core=True),
    ModuleDef("weather", "离线天气预测 — 气压/云图", "Weather Prediction — barometer/cloud guide", "sensor_hub"),
    ModuleDef("psychology", "心理状态追踪 — 孤独/压力/干预", "Psychology Tracker — loneliness/stress/intervention", "self_learning"),
    ModuleDef("gps_manager", "GPS 管理器 — 定位/轨迹", "GPS Manager — positioning/tracking", "sensor_hub"),
    ModuleDef("environment", "环境评估 — 气候/威胁/机会", "Environment Assessor — climate/threats/opportunity", "sensor_hub"),
    ModuleDef("voice", "语音交互 — Whisper STT + TTS", "Voice Interaction — Whisper STT + TTS", "voice_input"),
]


class ModuleRegistry:
    def __init__(self, flags: FeatureFlags):
        self.flags = flags
        self._modules: dict[str, ModuleDef] = {}
        self._loaded: dict[str, Any] = {}
        self._disabled: set[str] = set()
        for mod in MODULE_DEFINITIONS:
            self._modules[mod.name] = ModuleDef(
                name=mod.name,
                description_zh=mod.description_zh,
                description_en=mod.description_en,
                feature_flag=mod.feature_flag,
                is_core=mod.is_core,
            )

    def should_load(self, module_name: str) -> bool:
        if module_name in self._disabled:
            return False
        mod = self._modules.get(module_name)
        if not mod:
            return False
        if mod.is_core:
            return True
        return bool(getattr(self.flags, mod.feature_flag, False))

    def register(self, module_name: str, instance: Any) -> bool:
        if not self.should_load(module_name):
            return False
        self._loaded[module_name] = instance
        self._modules[module_name].instance = instance
        return True

    def get(self, module_name: str) -> Optional[Any]:
        return self._loaded.get(module_name)

    def is_loaded(self, module_name: str) -> bool:
        return module_name in self._loaded

    def is_available(self, module_name: str) -> bool:
        mod = self._modules.get(module_name)
        if not mod:
            return False
        return bool(getattr(self.flags, mod.feature_flag, False))

    def disable(self, module_name: str) -> bool:
        mod = self._modules.get(module_name)
        if not mod:
            return False
        if mod.is_core:
            return False
        self._disabled.add(module_name)
        self._loaded.pop(module_name, None)
        mod.instance = None
        return True

    def enable(self, module_name: str) -> bool:
        if module_name not in self._modules:
            return False
        self._disabled.discard(module_name)
        return True

    def get_status(self, lang: str = "zh") -> list[dict]:
        result = []
        for name, mod in self._modules.items():
            desc = mod.description_zh if lang == "zh" else mod.description_en
            result.append({
                "name": name,
                "description": desc,
                "is_core": mod.is_core,
                "flag_enabled": bool(getattr(self.flags, mod.feature_flag, False)),
                "loaded": name in self._loaded,
                "disabled": name in self._disabled,
                "can_load": self.should_load(name),
            })
        return result

    def get_active_modules(self) -> list[str]:
        return list(self._loaded.keys())

    def get_disabled_by_hardware(self) -> list[str]:
        result = []
        for name, mod in self._modules.items():
            if not mod.is_core and not getattr(self.flags, mod.feature_flag, False):
                result.append(name)
        return result

    def format_status(self, lang: str = "zh") -> str:
        from rich.console import Console
        from rich.table import Table

        from allspark.core.i18n import t

        console = Console()
        title = t("title_module_status")
        table = Table(title=title, show_header=True, header_style="bold")
        table.add_column(t("field_module"), style="cyan")
        table.add_column(t("field_description"))
        table.add_column(t("field_core"), justify="center")
        table.add_column(t("field_hardware"), justify="center")
        table.add_column(t("field_status_col"), justify="center")

        for name, mod in self._modules.items():
            desc = mod.description_zh if lang == "zh" else mod.description_en
            is_core = "⭐" if mod.is_core else ""
            flag_on = bool(getattr(self.flags, mod.feature_flag, False))
            hw_icon = t("hw_ok") if flag_on else t("hw_insufficient")

            if name in self._disabled:
                status = t("module_manual_disabled")
            elif name in self._loaded:
                status = t("module_loaded")
            elif not flag_on:
                status = t("hw_insufficient")
            else:
                status = t("module_pending")

            table.add_row(name, desc, is_core, hw_icon, status)

        with console.capture() as capture:
            console.print(table)
        return capture.get()

    def format_status_dict(self) -> list[dict]:
        result = []
        for name, mod in self._modules.items():
            flag_on = bool(getattr(self.flags, mod.feature_flag, False))
            if name in self._disabled:
                status = "disabled"
            elif name in self._loaded:
                status = "loaded"
            elif not flag_on:
                status = "unsupported"
            else:
                status = "available"
            result.append({
                "name": name,
                "description_en": mod.description_en,
                "description_zh": mod.description_zh,
                "is_core": mod.is_core,
                "feature_flag": mod.feature_flag,
                "hw_supported": flag_on,
                "status": status,
            })
        return result

    def save_to_db(self, db):
        import json
        flags_dict = {}
        for attr in [
            "rule_engine", "sqlite_fts", "vector_rag", "kiwix",
            "llm", "llm_model", "multilingual_knowledge",
            "text_interaction", "image_recognition", "voice_input",
            "voice_output", "web_ui", "offline_map", "kolibri",
            "spark_network", "multimodal", "self_learning",
            "governance", "trade_engine", "power_monitor",
            "sensor_hub", "data_preservation", "boot_manager",
        ]:
            val = getattr(self.flags, attr, None)
            if val is not None:
                flags_dict[attr] = val

        db.save_hardware_profile("feature_flags", json.dumps(flags_dict, ensure_ascii=False))
        db.save_hardware_profile("disabled_modules", json.dumps(list(self._disabled), ensure_ascii=False))

    @classmethod
    def load_from_db(cls, db) -> Optional["ModuleRegistry"]:
        import json
        profile = db.get_hardware_profile()
        flags_json = profile.get("feature_flags")
        if not flags_json:
            return None

        try:
            flags_dict = json.loads(flags_json)
        except (json.JSONDecodeError, TypeError):
            return None

        flags = FeatureFlags()
        for k, v in flags_dict.items():
            if hasattr(flags, k):
                setattr(flags, k, v)

        registry = cls(flags)

        disabled_json = profile.get("disabled_modules", "[]")
        try:
            disabled = json.loads(disabled_json)
            registry._disabled = set(disabled)
        except (json.JSONDecodeError, TypeError):
            pass

        return registry
