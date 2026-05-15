import os
import platform
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class HardwareTier(Enum):
    PHANTOM = "phantom"
    MINIMUM = "minimum"
    RECOMMENDED = "recommended"
    COMFORTABLE = "comfortable"
    FLAGSHIP = "flagship"


@dataclass
class HardwareProfile:
    cpu_arch: str = ""
    cpu_model: str = ""
    cpu_cores: int = 0
    ram_total_gb: float = 0.0
    ram_available_gb: float = 0.0
    storage_total_gb: float = 0.0
    storage_available_gb: float = 0.0
    gpu_info: str = ""
    gpu_available: bool = False
    os_name: str = ""
    os_version: str = ""
    hostname: str = ""
    tier: HardwareTier = HardwareTier.MINIMUM


@dataclass
class FeatureFlags:
    rule_engine: bool = True
    sqlite_fts: bool = True
    vector_rag: bool = False
    kiwix: bool = False
    llm: bool = False
    llm_model: str = ""
    multilingual_knowledge: bool = True
    text_interaction: bool = True
    image_recognition: bool = False
    voice_input: bool = False
    voice_output: bool = False
    web_ui: bool = False
    offline_map: bool = False
    kolibri: bool = False
    spark_network: bool = True
    multimodal: bool = False
    self_learning: bool = False
    governance: bool = False
    trade_engine: bool = False
    power_monitor: bool = False
    sensor_hub: bool = False
    data_preservation: bool = False
    boot_manager: bool = False


TIER_THRESHOLDS = {
    HardwareTier.PHANTOM: {"ram_gb": 0, "storage_gb": 0},
    HardwareTier.MINIMUM: {"ram_gb": 4, "storage_gb": 32},
    HardwareTier.RECOMMENDED: {"ram_gb": 8, "storage_gb": 64},
    HardwareTier.COMFORTABLE: {"ram_gb": 16, "storage_gb": 128},
    HardwareTier.FLAGSHIP: {"ram_gb": 32, "storage_gb": 256},
}

LLM_MODEL_MAP = {
    HardwareTier.PHANTOM: {"model": "Qwen2.5-1.5B-Q4", "size_gb": 1, "speed_tps": "~1"},
    HardwareTier.MINIMUM: {"model": "Qwen2.5-3B-Q4", "size_gb": 2, "speed_tps": "~3"},
    HardwareTier.RECOMMENDED: {"model": "Qwen2.5-7B-Q4", "size_gb": 4.5, "speed_tps": "~8"},
    HardwareTier.COMFORTABLE: {"model": "Qwen2.5-14B-Q4", "size_gb": 9, "speed_tps": "~15"},
    HardwareTier.FLAGSHIP: {"model": "Qwen2.5-72B-Q4", "size_gb": 40, "speed_tps": "~50"},
}


def detect_hardware() -> HardwareProfile:
    profile = HardwareProfile()
    profile.os_name = platform.system()
    profile.os_version = platform.release()
    profile.hostname = platform.node()
    profile.cpu_arch = platform.machine()
    profile.cpu_model = platform.processor() or "Unknown"
    profile.cpu_cores = os.cpu_count() or 1

    _detect_ram(profile)
    _detect_storage(profile)
    _detect_gpu(profile)
    profile.tier = _classify_tier(profile)

    return profile


def _detect_ram(profile: HardwareProfile):
    try:
        if profile.os_name == "Darwin":
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                profile.ram_total_gb = int(result.stdout.strip()) / (1024 ** 3)
            result2 = subprocess.run(
                ["vm_stat"],
                capture_output=True, text=True, timeout=5
            )
            if result2.returncode == 0:
                for line in result2.stdout.split("\n"):
                    if "Pages free" in line or "page size" in line.lower():
                        pass
                profile.ram_available_gb = profile.ram_total_gb * 0.6
        elif profile.os_name == "Linux":
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    parts = line.split()
                    if parts[0] == "MemTotal:":
                        profile.ram_total_gb = int(parts[1]) / (1024 ** 2)
                    elif parts[0] == "MemAvailable:":
                        profile.ram_available_gb = int(parts[1]) / (1024 ** 2)
        else:
            profile.ram_total_gb = 4.0
            profile.ram_available_gb = 2.0
    except Exception:
        profile.ram_total_gb = 4.0
        profile.ram_available_gb = 2.0


def _detect_storage(profile: HardwareProfile):
    try:
        if profile.os_name == "Darwin" or profile.os_name == "Linux":
            stat = os.statvfs("/")
            profile.storage_total_gb = (stat.f_blocks * stat.f_frsize) / (1024 ** 3)
            profile.storage_available_gb = (stat.f_bavail * stat.f_frsize) / (1024 ** 3)
        else:
            profile.storage_total_gb = 32.0
            profile.storage_available_gb = 16.0
    except Exception:
        profile.storage_total_gb = 32.0
        profile.storage_available_gb = 16.0


def _detect_gpu(profile: HardwareProfile):
    profile.gpu_available = False
    profile.gpu_info = "None"
    try:
        if profile.os_name == "Linux":
            result = subprocess.run(
                ["lspci"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    if "VGA" in line or "3D" in line or "NVIDIA" in line or "AMD" in line:
                        profile.gpu_available = True
                        profile.gpu_info = line.strip()
                        break
        elif profile.os_name == "Darwin":
            result = subprocess.run(
                ["system_profiler", "SPDisplaysDataType"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    if "Chipset Model" in line or "Metal" in line:
                        profile.gpu_available = True
                        profile.gpu_info = line.strip()
                        break
    except Exception:
        pass


def _classify_tier(profile: HardwareProfile) -> HardwareTier:
    ram = profile.ram_total_gb
    storage = profile.storage_available_gb

    if ram >= 32 and storage >= 256:
        return HardwareTier.FLAGSHIP
    elif ram >= 16 and storage >= 128:
        return HardwareTier.COMFORTABLE
    elif ram >= 8 and storage >= 64:
        return HardwareTier.RECOMMENDED
    elif ram >= 4 and storage >= 32:
        return HardwareTier.MINIMUM
    else:
        return HardwareTier.PHANTOM


def compute_feature_flags(tier: HardwareTier, gpu_available: bool = False) -> FeatureFlags:
    flags = FeatureFlags()

    if tier == HardwareTier.PHANTOM:
        flags.vector_rag = False
        flags.kiwix = False
        flags.llm = True
        flags.llm_model = LLM_MODEL_MAP[tier]["model"]
        flags.multilingual_knowledge = False
        flags.image_recognition = False
        flags.voice_input = False
        flags.voice_output = False
        flags.web_ui = False
        flags.offline_map = False
        flags.kolibri = False
        flags.multimodal = False
        flags.self_learning = False
        flags.governance = False
        flags.trade_engine = False
        flags.power_monitor = False
        flags.sensor_hub = False
        flags.data_preservation = False
        flags.boot_manager = False

    elif tier == HardwareTier.MINIMUM:
        flags.vector_rag = True
        flags.kiwix = True
        flags.llm = True
        flags.llm_model = LLM_MODEL_MAP[tier]["model"]
        flags.multilingual_knowledge = True
        flags.image_recognition = gpu_available
        flags.voice_input = False
        flags.voice_output = False
        flags.web_ui = gpu_available
        flags.offline_map = True
        flags.kolibri = gpu_available
        flags.multimodal = False
        flags.self_learning = True
        flags.governance = False
        flags.trade_engine = False
        flags.power_monitor = gpu_available
        flags.sensor_hub = False
        flags.data_preservation = True
        flags.boot_manager = False

    elif tier == HardwareTier.RECOMMENDED:
        flags.vector_rag = True
        flags.kiwix = True
        flags.llm = True
        flags.llm_model = LLM_MODEL_MAP[tier]["model"]
        flags.multilingual_knowledge = True
        flags.image_recognition = True
        flags.voice_input = gpu_available
        flags.voice_output = gpu_available
        flags.web_ui = True
        flags.offline_map = True
        flags.kolibri = True
        flags.multimodal = gpu_available
        flags.self_learning = True
        flags.governance = True
        flags.trade_engine = gpu_available
        flags.power_monitor = True
        flags.sensor_hub = gpu_available
        flags.data_preservation = True
        flags.boot_manager = gpu_available

    elif tier in (HardwareTier.COMFORTABLE, HardwareTier.FLAGSHIP):
        flags.vector_rag = True
        flags.kiwix = True
        flags.llm = True
        flags.llm_model = LLM_MODEL_MAP[tier]["model"]
        flags.multilingual_knowledge = True
        flags.image_recognition = True
        flags.voice_input = True
        flags.voice_output = True
        flags.web_ui = True
        flags.offline_map = True
        flags.kolibri = True
        flags.multimodal = True
        flags.self_learning = True
        flags.governance = True
        flags.trade_engine = True
        flags.power_monitor = True
        flags.sensor_hub = True
        flags.data_preservation = True
        flags.boot_manager = True

    return flags


def format_hardware_report(profile: HardwareProfile, flags: FeatureFlags, lang: str = "zh") -> str:
    if lang == "en":
        tier_names = {
            HardwareTier.PHANTOM: "Phantom (2GB)",
            HardwareTier.MINIMUM: "Minimum (4GB)",
            HardwareTier.RECOMMENDED: "Recommended (8GB)",
            HardwareTier.COMFORTABLE: "Comfortable (16GB)",
            HardwareTier.FLAGSHIP: "Flagship (32GB+)",
        }
        lines = [
            "═══ Hardware Detection Report ═══",
            f"Tier: {tier_names.get(profile.tier, profile.tier.value)}",
            f"OS: {profile.os_name} {profile.os_version}",
            f"CPU: {profile.cpu_model} ({profile.cpu_cores} cores, {profile.cpu_arch})",
            f"RAM: {profile.ram_total_gb:.1f} GB (available: {profile.ram_available_gb:.1f} GB)",
            f"Storage: {profile.storage_available_gb:.1f} / {profile.storage_total_gb:.1f} GB available",
            f"GPU: {profile.gpu_info}",
            "",
            "═══ Feature Availability ═══",
        ]
        feature_labels = {
            "rule_engine": "Rule Engine",
            "sqlite_fts": "SQLite FTS",
            "vector_rag": "Vector RAG",
            "kiwix": "Kiwix Wikipedia",
            "llm": f"LLM ({flags.llm_model})",
            "multilingual_knowledge": "Multilingual Knowledge",
            "text_interaction": "Text Interaction",
            "image_recognition": "Image Recognition",
            "voice_input": "Voice Input",
            "voice_output": "Voice Output",
            "web_ui": "Web UI",
            "offline_map": "Offline Map",
            "kolibri": "Khan Academy (Kolibri)",
            "spark_network": "AllSpark Network",
            "multimodal": "Multimodal",
            "self_learning": "Self-Learning",
            "governance": "Governance",
            "trade_engine": "Trade Engine",
            "power_monitor": "Power Monitor",
            "sensor_hub": "Sensor Hub",
            "data_preservation": "Data Preservation",
            "boot_manager": "Boot Manager",
        }
    else:
        tier_names = {
            HardwareTier.PHANTOM: "残影模式 (2GB)",
            HardwareTier.MINIMUM: "最低配置 (4GB)",
            HardwareTier.RECOMMENDED: "推荐配置 (8GB)",
            HardwareTier.COMFORTABLE: "舒适配置 (16GB)",
            HardwareTier.FLAGSHIP: "旗舰配置 (32GB+)",
        }
        lines = [
            "═══ 硬件检测报告 ═══",
            f"配置等级：{tier_names.get(profile.tier, profile.tier.value)}",
            f"操作系统：{profile.os_name} {profile.os_version}",
            f"处理器：{profile.cpu_model}（{profile.cpu_cores} 核，{profile.cpu_arch}）",
            f"内存：{profile.ram_total_gb:.1f} GB（可用 {profile.ram_available_gb:.1f} GB）",
            f"存储：{profile.storage_available_gb:.1f} / {profile.storage_total_gb:.1f} GB 可用",
            f"显卡：{profile.gpu_info}",
            "",
            "═══ 功能可用性 ═══",
        ]
        feature_labels = {
            "rule_engine": "规则引擎",
            "sqlite_fts": "SQLite 全文检索",
            "vector_rag": "向量检索 (RAG)",
            "kiwix": "Kiwix 维基百科",
            "llm": f"LLM（{flags.llm_model}）",
            "multilingual_knowledge": "多语言知识库",
            "text_interaction": "纯文字交互",
            "image_recognition": "图片识别",
            "voice_input": "语音输入",
            "voice_output": "语音输出",
            "web_ui": "Web UI",
            "offline_map": "离线地图",
            "kolibri": "可汗学院 (Kolibri)",
            "spark_network": "火种通信",
            "multimodal": "多模态交互",
            "self_learning": "自学习沉淀",
            "governance": "社区治理",
            "trade_engine": "知识交易",
            "power_monitor": "电力监控",
            "sensor_hub": "传感器",
            "data_preservation": "数据固化",
            "boot_manager": "启动优化",
        }

    for attr, label in feature_labels.items():
        val = getattr(flags, attr)
        icon = "✅" if val else "❌"
        lines.append(f"  {icon} {label}")

    return "\n".join(lines)
