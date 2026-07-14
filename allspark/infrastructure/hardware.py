import os
import platform
import subprocess
from dataclasses import dataclass, field
from enum import Enum


class HardwareTier(Enum):
    PHANTOM = "phantom"
    MINIMUM = "minimum"
    RECOMMENDED = "recommended"
    COMFORTABLE = "comfortable"
    FLAGSHIP = "flagship"


class DeployMode(Enum):
    PROCESS = "process"
    DOCKER = "docker"
    INTEGRATION = "integration"


DEPLOY_MODE_MAP = {
    HardwareTier.PHANTOM: DeployMode.PROCESS,
    HardwareTier.MINIMUM: DeployMode.PROCESS,
    HardwareTier.RECOMMENDED: DeployMode.DOCKER,
    HardwareTier.COMFORTABLE: DeployMode.DOCKER,
    HardwareTier.FLAGSHIP: DeployMode.INTEGRATION,
}


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
    deploy_mode: DeployMode = DeployMode.PROCESS


@dataclass
class FeatureFlags:
    rule_engine: bool = True
    sqlite_fts: bool = True
    vector_rag: bool = False
    kiwix: bool = False
    llm: bool = False
    llm_model: str = ""
    tier: HardwareTier = HardwareTier.MINIMUM
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
    deploy_mode: str = "process"
    docker_enabled: bool = False
    docker_services: list = field(default_factory=list)
    recommended_deploy_mode: str = "process"
    docker_eligible: bool = False
    docker_available: bool = False
    recommended_docker_services: list = field(default_factory=list)


TIER_THRESHOLDS = {
    HardwareTier.PHANTOM: {"ram_gb": 0, "storage_gb": 0},
    HardwareTier.MINIMUM: {"ram_gb": 4, "storage_gb": 32},
    HardwareTier.RECOMMENDED: {"ram_gb": 8, "storage_gb": 64},
    HardwareTier.COMFORTABLE: {"ram_gb": 16, "storage_gb": 128},
    HardwareTier.FLAGSHIP: {"ram_gb": 32, "storage_gb": 256},
}

LLM_MODEL_MAP = {
    HardwareTier.PHANTOM: {"model": "qwen3-1_7b-instruct-q4", "size_gb": 1, "speed_tps": "~2"},
    HardwareTier.MINIMUM: {"model": "qwen3-4b-instruct-q4", "size_gb": 2.5, "speed_tps": "~5"},
    HardwareTier.RECOMMENDED: {"model": "qwen3-8b-instruct-q4", "size_gb": 5, "speed_tps": "~10"},
    HardwareTier.COMFORTABLE: {"model": "qwen3-14b-instruct-q4", "size_gb": 9, "speed_tps": "~18"},
    HardwareTier.FLAGSHIP: {"model": "qwen3-32b-instruct-q4", "size_gb": 20, "speed_tps": "~35"},
}
# NOTE: this dict is kept for backward compatibility with code that
# expects the old shape. The single source of truth is
# `allspark/data/models.yaml`, exposed via
# `allspark.services.model_registry`. Any update here MUST stay in sync
# with `recommendations:` in models.yaml.


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
    profile.deploy_mode = DEPLOY_MODE_MAP.get(profile.tier, DeployMode.PROCESS)

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
    # Lazy import to avoid circular dependency: model_registry imports
    # HardwareTier from this module.
    from allspark.services.model_registry import resolve_model_name

    flags = FeatureFlags()
    flags.tier = tier
    llm_model = resolve_model_name(tier)

    if tier == HardwareTier.PHANTOM:
        flags.vector_rag = False
        flags.kiwix = False
        flags.llm = True
        flags.llm_model = llm_model
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
        flags.llm_model = llm_model
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
        flags.llm_model = llm_model
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
        flags.llm_model = llm_model
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

    deploy_mode = DEPLOY_MODE_MAP.get(tier, DeployMode.PROCESS)
    flags.deploy_mode = deploy_mode.value
    flags.recommended_deploy_mode = deploy_mode.value
    flags.docker_eligible = deploy_mode in (DeployMode.DOCKER, DeployMode.INTEGRATION)
    if deploy_mode in (DeployMode.DOCKER, DeployMode.INTEGRATION):
        flags.docker_enabled = True
        docker_svcs = ["web"]
        if flags.llm:
            docker_svcs.append("llm")
        if flags.vector_rag:
            docker_svcs.append("rag")
        if flags.kiwix:
            docker_svcs.append("kiwix")
        flags.docker_services = docker_svcs
        flags.recommended_docker_services = list(docker_svcs)

    return flags


def resolve_runtime_deploy_mode(
    flags: FeatureFlags,
    docker_available: bool,
) -> FeatureFlags:
    """Resolve a hardware recommendation into the verified runtime mode."""
    flags.docker_available = docker_available
    recommended = flags.recommended_deploy_mode
    docker_target = recommended in {
        DeployMode.DOCKER.value,
        DeployMode.INTEGRATION.value,
    }
    if docker_target and docker_available:
        flags.deploy_mode = recommended
        flags.docker_enabled = True
        flags.docker_services = list(flags.recommended_docker_services)
    else:
        flags.deploy_mode = DeployMode.PROCESS.value
        flags.docker_enabled = False
        flags.docker_services = []
    return flags


def format_hardware_report(
    profile: HardwareProfile,
    flags: FeatureFlags,
    lang: str = "zh",
    capabilities: list[dict] | None = None,
) -> str:
    if capabilities is None:
        from allspark.infrastructure.module_loader import ModuleRegistry

        capabilities = ModuleRegistry(flags).format_status_dict()

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
            "═══ Capability Preflight ═══",
        ]
        feature_labels = {
            "rule_engine": "Rule Engine",
            "knowledge_fts": "SQLite FTS",
            "knowledge_vector": "Vector RAG",
            "kiwix": "Kiwix Wikipedia",
            "llm": f"LLM ({flags.llm_model})",
            "multilingual": "Multilingual Knowledge",
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
        dimension_labels = {
            "hardware_true": "Hardware capable",
            "hardware_false": "Hardware unsupported",
            "dependency_true": "Dependency installed",
            "dependency_false": "Missing dependency",
            "configured_true": "Configured",
            "configured_false": "Not configured",
            "running_true": "Running",
            "running_false": "Not running",
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
            "═══ 能力预检 ═══",
        ]
        feature_labels = {
            "rule_engine": "规则引擎",
            "knowledge_fts": "SQLite 全文检索",
            "knowledge_vector": "向量检索 (RAG)",
            "kiwix": "Kiwix 维基百科",
            "llm": f"LLM（{flags.llm_model}）",
            "multilingual": "多语言知识库",
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
        dimension_labels = {
            "hardware_true": "硬件支持",
            "hardware_false": "硬件不支持",
            "dependency_true": "依赖已安装",
            "dependency_false": "缺少依赖",
            "configured_true": "已配置",
            "configured_false": "未配置",
            "running_true": "运行中",
            "running_false": "未运行",
        }

    capability_map = {item["name"]: item for item in capabilities}
    for name, label in feature_labels.items():
        capability = capability_map.get(name)
        if not capability:
            continue
        details = [
            dimension_labels[
                f"hardware_{str(bool(capability['hardware_capable'])).lower()}"
            ],
            dimension_labels[
                f"dependency_{str(bool(capability['dependency_installed'])).lower()}"
            ],
            dimension_labels[
                f"configured_{str(bool(capability['configured'])).lower()}"
            ],
            dimension_labels[
                f"running_{str(bool(capability['running'])).lower()}"
            ],
        ]
        marker = "◇" if capability["hardware_capable"] else "✗"
        experimental = " [EXP]" if capability["experimental"] else ""
        lines.append(f"  {marker} {label}{experimental} — {'; '.join(details)}")

    deploy_mode = flags.deploy_mode
    recommended_mode = flags.recommended_deploy_mode
    if lang == "en":
        deploy_names = {
            "process": "Process Mode",
            "docker": "Docker Mode",
            "integration": "Integration Mode (Docker + NOMAD)",
        }
        lines.append("")
        lines.append("═══ Deployment Mode ═══")
        lines.append(
            f"  Eligible target: {deploy_names.get(recommended_mode, recommended_mode)}"
        )
        docker_state = "Available" if flags.docker_available else "Unavailable"
        lines.append(f"  Docker daemon: {docker_state}")
        lines.append(f"  Actual mode: {deploy_names.get(deploy_mode, deploy_mode)}")
        if flags.recommended_docker_services:
            lines.append(
                "  Planned container services: "
                + ", ".join(flags.recommended_docker_services)
            )
    else:
        deploy_names = {
            "process": "进程模式",
            "docker": "Docker 模式",
            "integration": "集成模式（Docker + NOMAD）",
        }
        lines.append("")
        lines.append("═══ 部署模式 ═══")
        lines.append(
            f"  硬件建议目标：{deploy_names.get(recommended_mode, recommended_mode)}"
        )
        docker_state = "可用" if flags.docker_available else "不可用"
        lines.append(f"  Docker 守护进程：{docker_state}")
        lines.append(f"  实际模式：{deploy_names.get(deploy_mode, deploy_mode)}")
        if flags.recommended_docker_services:
            lines.append(
                f"  计划容器服务：{'、'.join(flags.recommended_docker_services)}"
            )

    return "\n".join(lines)
