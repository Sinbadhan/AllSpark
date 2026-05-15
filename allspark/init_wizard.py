import urllib.request
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, BarColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn
from rich.text import Text
from rich.table import Table

from allspark.config import DEFAULT_DB_DIR
from allspark.database import Database
from allspark.hardware import (
    detect_hardware, compute_feature_flags,
    format_hardware_report, HardwareTier, LLM_MODEL_MAP
)
from allspark.i18n import t, set_language, get_language
from allspark.module_loader import ModuleRegistry

console = Console()

MODELS_DIR = DEFAULT_DB_DIR / "models"

MODEL_DOWNLOAD_URLS = {
    "Qwen2.5-1.5B-Q4": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
    "Qwen2.5-3B-Q4": "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf",
    "Qwen2.5-7B-Q4": "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/qwen2.5-7b-instruct-q4_k_m.gguf",
    "Qwen2.5-14B-Q4": "https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF/resolve/main/qwen2.5-14b-instruct-q4_k_m.gguf",
    "Qwen2.5-32B-Q4": "https://huggingface.co/Qwen/Qwen2.5-32B-Instruct-GGUF/resolve/main/qwen2.5-32b-instruct-q4_k_m.gguf",
    "Qwen2.5-72B-Q4": "https://huggingface.co/Qwen/Qwen2.5-72B-Instruct-GGUF/resolve/main/qwen2.5-72b-instruct-q4_k_m.gguf",
}


def run_init_wizard(db: Database) -> dict:
    console.print(Panel(
        Text.assemble(
            ("🔥 火 种 / AllSpark\n", "bold red"),
            ("AllSpark: A Survival-centric Offline AI Resource Kit\n", "dim"),
            ("━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n", "dim"),
            ("初次启动，需要完成初始化配置。\n", "white"),
            ("这个过程只需要一次，之后火种会记住你的设置。\n", "dim"),
        ),
        title="⚡ 初始化",
        border_style="red",
        padding=(1, 2)
    ))

    result = {}

    result["language"] = _step_language_select()

    lang = get_language()
    title_text = "初始化" if lang == "zh" else "Initialization"
    console.print(Panel(
        Text.assemble(
            ("🔥 火 种 / AllSpark\n", "bold red"),
            ("AllSpark: A Survival-centric Offline AI Resource Kit\n", "dim"),
            ("━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n", "dim"),
            ("初次启动，需要完成初始化配置。\n" if lang == "zh" else "First launch — initial setup required.\n", "white"),
            ("这个过程只需要一次，之后火种会记住你的设置。\n" if lang == "zh" else "This only happens once. AllSpark will remember your settings.\n", "dim"),
        ),
        title=f"⚡ {title_text}",
        border_style="red",
        padding=(1, 2)
    ))

    result["hardware"] = _step_hardware_detect(db)
    result["model"] = _step_model_setup(db, result["hardware"])
    result["survivor"] = _step_survivor_profile(db)
    result["personality"] = _step_personality_init(db)

    _step_summary(result)

    db.mark_initialized()

    if lang == "zh":
        console.print("\n[bold green]✓ 初始化完成！火种已就绪。[/]")
        console.print("[dim]输入 '帮助' 查看可用命令。[/]\n")
    else:
        console.print("\n[bold green]✓ Initialization complete! AllSpark is ready.[/]")
        console.print("[dim]Type 'help' to see available commands.[/]\n")

    return result


def _step_hardware_detect(db: Database) -> dict:
    lang = get_language()
    step_label = "步骤 2/5：硬件自检" if lang == "zh" else "Step 2/5: Hardware Detection"
    console.print(f"\n[bold cyan]━━ {step_label} ━━[/]")
    detecting = "正在检测硬件配置..." if lang == "zh" else "Detecting hardware..."
    console.print(f"[dim]{detecting}[/]\n")

    profile = detect_hardware()
    flags = compute_feature_flags(profile.tier, profile.gpu_available)

    report = format_hardware_report(profile, flags, lang=lang)
    console.print(report)

    if profile.tier == HardwareTier.PHANTOM:
        if lang == "zh":
            console.print("\n[yellow]⚠️ 当前硬件低于官方最低配置，部分功能将受限。[/]")
            console.print("[dim]建议：寻找至少 4GB RAM 的设备以获得完整火种体验。[/]")
        else:
            console.print("\n[yellow]⚠️ Hardware below minimum specs. Some features will be limited.[/]")
            console.print("[dim]Suggestion: Find a device with at least 4GB RAM for the full AllSpark experience.[/]")

    selected_tier = _ask_tier_override(profile.tier, lang)
    if selected_tier != profile.tier:
        profile.tier = selected_tier
        flags = compute_feature_flags(selected_tier, profile.gpu_available)
        tier_names_zh = {
            HardwareTier.PHANTOM: "残影模式", HardwareTier.MINIMUM: "最低配置",
            HardwareTier.RECOMMENDED: "推荐配置", HardwareTier.COMFORTABLE: "舒适配置",
            HardwareTier.FLAGSHIP: "旗舰配置",
        }
        tier_names_en = {
            HardwareTier.PHANTOM: "Phantom", HardwareTier.MINIMUM: "Minimum",
            HardwareTier.RECOMMENDED: "Recommended", HardwareTier.COMFORTABLE: "Comfortable",
            HardwareTier.FLAGSHIP: "Flagship",
        }
        tier_name = tier_names_zh.get(selected_tier, selected_tier.value) if lang == "zh" else tier_names_en.get(selected_tier, selected_tier.value)
        if lang == "zh":
            console.print(f"\n[green]✓ 已选择配置等级：{tier_name}[/]")
        else:
            console.print(f"\n[green]✓ Selected tier: {tier_name}[/]")
        updated_report = format_hardware_report(profile, flags, lang=lang)
        console.print(updated_report)

    for key, val in [
        ("cpu_arch", profile.cpu_arch),
        ("cpu_model", profile.cpu_model),
        ("cpu_cores", str(profile.cpu_cores)),
        ("ram_total_gb", f"{profile.ram_total_gb:.1f}"),
        ("ram_available_gb", f"{profile.ram_available_gb:.1f}"),
        ("storage_total_gb", f"{profile.storage_total_gb:.1f}"),
        ("storage_available_gb", f"{profile.storage_available_gb:.1f}"),
        ("gpu_info", profile.gpu_info),
        ("gpu_available", str(profile.gpu_available)),
        ("os_name", profile.os_name),
        ("os_version", profile.os_version),
        ("tier", profile.tier.value),
    ]:
        db.save_hardware_profile(key, val)

    registry = ModuleRegistry(flags)
    registry.save_to_db(db)

    return {"profile": profile, "flags": flags}


def _ask_tier_override(detected_tier: HardwareTier, lang: str) -> HardwareTier:
    tier_order = [
        HardwareTier.PHANTOM, HardwareTier.MINIMUM, HardwareTier.RECOMMENDED,
        HardwareTier.COMFORTABLE, HardwareTier.FLAGSHIP,
    ]
    detected_idx = tier_order.index(detected_tier)
    if detected_idx == 0:
        return detected_tier

    tier_names_zh = {
        HardwareTier.PHANTOM: "残影模式 (2GB)", HardwareTier.MINIMUM: "最低配置 (4GB)",
        HardwareTier.RECOMMENDED: "推荐配置 (8GB)", HardwareTier.COMFORTABLE: "舒适配置 (16GB)",
        HardwareTier.FLAGSHIP: "旗舰配置 (32GB+)",
    }
    tier_names_en = {
        HardwareTier.PHANTOM: "Phantom (2GB)", HardwareTier.MINIMUM: "Minimum (4GB)",
        HardwareTier.RECOMMENDED: "Recommended (8GB)", HardwareTier.COMFORTABLE: "Comfortable (16GB)",
        HardwareTier.FLAGSHIP: "Flagship (32GB+)",
    }
    tier_names = tier_names_zh if lang == "zh" else tier_names_en

    if lang == "zh":
        console.print(f"\n[dim]检测到配置等级：{tier_names[detected_tier]}[/]")
        console.print("[dim]你可以选择更低的配置以节省资源，或保持自动检测结果。[/]")
        console.print("选择配置等级：")
    else:
        console.print(f"\n[dim]Detected tier: {tier_names[detected_tier]}[/]")
        console.print("[dim]You can choose a lower tier to save resources, or keep the auto-detected result.[/]")
        console.print("Choose hardware tier:")

    for i, tier in enumerate(tier_order):
        if i <= detected_idx:
            marker = " ←" if tier == detected_tier else ""
            console.print(f"  {i + 1}. {tier_names[tier]}{marker}")

    keep_label = "保持自动检测" if lang == "zh" else "Keep auto-detected"
    console.print(f"  0. {keep_label}")

    while True:
        choice = console.input("\n🔥 [0-{}] > ".format(detected_idx + 1)).strip()
        if choice == "0":
            return detected_tier
        try:
            idx = int(choice) - 1
            if 0 <= idx <= detected_idx:
                return tier_order[idx]
        except ValueError:
            pass
        if lang == "zh":
            console.print("[red]请输入有效编号[/]")
        else:
            console.print("[red]Enter a valid number[/]")


def _step_language_select() -> str:
    lang = get_language()
    step_label = "步骤 1/5：语言设置" if lang == "zh" else "Step 1/5: Language"
    console.print(f"\n[bold cyan]━━ {step_label} ━━[/]")
    console.print("[dim]Choose your language / 选择你的语言：[/]")
    console.print("  1. 中文 (zh)")
    console.print("  2. English (en)")

    while True:
        choice = console.input("\n🔥 [1/2] > ").strip()
        if choice in ("1", "zh", "中文"):
            set_language("zh")
            console.print("[green]✓ 已选择中文[/]")
            return "zh"
        elif choice in ("2", "en", "english"):
            set_language("en")
            console.print("[green]✓ Language set to English[/]")
            return "en"
        else:
            console.print("[red]请输入 1 或 2[/]")


def _step_model_setup(db: Database, hw_result: dict) -> dict:
    lang = get_language()
    step_label = "步骤 3/5：AI 模型设置" if lang == "zh" else "Step 3/5: AI Model Setup"
    console.print(f"\n[bold cyan]━━ {step_label} ━━[/]")

    flags = hw_result.get("flags")
    profile = hw_result.get("profile")
    if not flags:
        return {"model": None, "downloaded": False}

    recommended = flags.llm_model
    model_info = LLM_MODEL_MAP.get(profile.tier, {})
    size_gb = model_info.get("size_gb", 0)

    if lang == "zh":
        console.print(f"根据你的硬件等级 [cyan]{profile.tier.value}[/]，推荐模型：[bold]{recommended}[/]")
        console.print(f"[dim]模型大小：约 {size_gb}GB | 估计速度：{model_info.get('speed_tps', '?')} tokens/s[/]")
    else:
        console.print(f"Based on your hardware tier [cyan]{profile.tier.value}[/], recommended model: [bold]{recommended}[/]")
        console.print(f"[dim]Model size: ~{size_gb}GB | Est. speed: {model_info.get('speed_tps', '?')} tokens/s[/]")

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    existing = list(MODELS_DIR.glob("*.gguf"))

    if existing:
        if lang == "zh":
            console.print(f"\n[green]✓ 已找到 {len(existing)} 个模型文件：[/]")
        else:
            console.print(f"\n[green]✓ Found {len(existing)} model file(s):[/]")
        for f in existing:
            size_mb = f.stat().st_size / (1024 * 1024)
            console.print(f"  [dim]• {f.name} ({size_mb:.0f} MB)[/]")

    model_downloaded = any(
        recommended.lower().replace("-", "").replace(".", "") in f.stem.lower().replace("-", "").replace(".", "")
        for f in existing
    )

    if model_downloaded:
        if lang == "zh":
            console.print(f"\n[green]✓ 推荐模型 {recommended} 已就绪[/]")
        else:
            console.print(f"\n[green]✓ Recommended model {recommended} is ready[/]")
        return {"model": recommended, "downloaded": True}

    if not flags.llm:
        if lang == "zh":
            console.print("\n[yellow]⚠️ 当前硬件不支持 LLM，将使用规则引擎提供生存建议。[/]")
            console.print("[dim]你可以在硬件升级后重新运行初始化来启用 LLM。[/]")
        else:
            console.print("\n[yellow]⚠️ Hardware does not support LLM. Rule engine will provide survival advice.[/]")
            console.print("[dim]You can re-run initialization after upgrading hardware.[/]")
        return {"model": None, "downloaded": False}

    if lang == "zh":
        console.print(f"\n[yellow]⬇️ 推荐模型尚未下载[/]")
        console.print("选择操作：")
        console.print(f"  1. 下载 {recommended}（推荐，约 {size_gb}GB）")
        console.print("  2. 跳过，稍后手动下载")
        console.print("  3. 选择其他模型")
    else:
        console.print(f"\n[yellow]⬇️ Recommended model not downloaded yet[/]")
        console.print("Choose an option:")
        console.print(f"  1. Download {recommended} (recommended, ~{size_gb}GB)")
        console.print("  2. Skip, download later")
        console.print("  3. Choose a different model")

    while True:
        choice = console.input("\n🔥 [1/2/3] > ").strip()
        if choice == "1":
            _download_model(recommended, size_gb, lang)
            return {"model": recommended, "downloaded": True}
        elif choice == "2":
            if lang == "zh":
                console.print("[dim]已跳过。你可以稍后使用 'llm load' 命令下载模型。[/]")
            else:
                console.print("[dim]Skipped. You can download the model later with 'llm load'.[/]")
            return {"model": recommended, "downloaded": False}
        elif choice == "3":
            return _choose_other_model(lang)
        else:
            if lang == "zh":
                console.print("[red]请输入 1、2 或 3[/]")
            else:
                console.print("[red]Enter 1, 2, or 3[/]")


def _choose_other_model(lang: str) -> dict:
    if lang == "zh":
        console.print("\n可用模型：")
    else:
        console.print("\nAvailable models:")

    model_keys = list(MODEL_DOWNLOAD_URLS.keys())
    for i, name in enumerate(model_keys, 1):
        info = LLM_MODEL_MAP.get(
            next((t for t in HardwareTier if LLM_MODEL_MAP.get(t, {}).get("model") == name), None),
            {}
        )
        size = info.get("size_gb", "?")
        speed = info.get("speed_tps", "?")
        console.print(f"  {i}. {name} (~{size}GB, ~{speed} t/s)")

    while True:
        choice = console.input("\n🔥 [1-6] > ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(model_keys):
                name = model_keys[idx]
                info = LLM_MODEL_MAP.get(
                    next((t for t in HardwareTier if LLM_MODEL_MAP.get(t, {}).get("model") == name), None),
                    {}
                )
                size_gb = info.get("size_gb", 2)
                _download_model(name, size_gb, lang)
                return {"model": name, "downloaded": True}
        except ValueError:
            pass
        if lang == "zh":
            console.print("[red]请输入有效编号[/]")
        else:
            console.print("[red]Enter a valid number[/]")


def _download_model(model_name: str, size_gb: float, lang: str):
    url = MODEL_DOWNLOAD_URLS.get(model_name)
    if not url:
        return

    filename = url.split("/")[-1]
    dest = MODELS_DIR / filename

    if dest.exists():
        if lang == "zh":
            console.print(f"[green]✓ 模型文件已存在：{dest}[/]")
        else:
            console.print(f"[green]✓ Model file already exists: {dest}[/]")
        return

    if lang == "zh":
        console.print(f"\n开始下载 {model_name}...")
        console.print(f"[dim]保存到：{dest}[/]")
        console.print("[dim]提示：下载大文件可能需要较长时间，取决于网络速度。[/]\n")
    else:
        console.print(f"\nDownloading {model_name}...")
        console.print(f"[dim]Saving to: {dest}[/]")
        console.print("[dim]Note: Large file download may take a while depending on network speed.[/]\n")

    tmp = dest.with_suffix(".tmp")

    try:
        with Progress(
            "[progress.description]{task.description}",
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.0f}%",
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(model_name, total=None)

            def _reporthook(block_num, block_size, total_size):
                progress.update(task, total=total_size, completed=block_num * block_size)

            urllib.request.urlretrieve(url, str(tmp), reporthook=_reporthook)

        tmp.rename(dest)
        if lang == "zh":
            console.print(f"\n[bold green]✓ 下载完成！模型已保存到 {dest}[/]")
        else:
            console.print(f"\n[bold green]✓ Download complete! Model saved to {dest}[/]")
    except Exception as e:
        if tmp.exists():
            tmp.unlink()
        if lang == "zh":
            console.print(f"\n[red]✗ 下载失败：{e}[/]")
            console.print("[dim]你可以稍后手动下载模型文件，放到 ~/.allspark/models/ 目录下。[/]")
        else:
            console.print(f"\n[red]✗ Download failed: {e}[/]")
            console.print("[dim]You can manually download the model file later and place it in ~/.allspark/models/[/]")


def _step_survivor_profile(db: Database) -> dict:
    lang = get_language()
    step_label = "步骤 4/5：生存者建档" if lang == "zh" else "Step 4/5: Survivor Profile"
    console.print(f"\n[bold cyan]━━ {step_label} ━━[/]")

    if lang == "zh":
        name_label = "你的名字/代号"
        situation_label = "当前处境描述（可选，如：独自在废墟中/在避难所/野外求生）"
        skills_label = "你的技能（逗号分隔，如：急救,烹饪,电子维修）"
        health_label = "当前健康状况（良好/轻伤/重伤/生病）"
        default_name = "生存者"
    else:
        name_label = "Your name/callsign"
        situation_label = "Current situation (optional, e.g.: alone in ruins / in shelter / in the wild)"
        skills_label = "Your skills (comma-separated, e.g.: first aid, cooking, electronics)"
        health_label = "Current health status (good / minor injury / severe injury / sick)"
        default_name = "Survivor"

    name = console.input(f"  {name_label}: ").strip() or default_name
    situation = console.input(f"  {situation_label}: ").strip()
    skills_str = console.input(f"  {skills_label}: ").strip()
    skills = [s.strip() for s in skills_str.split(",") if s.strip()]
    health = console.input(f"  {health_label}: ").strip() or "unknown"

    db.save_survivor_state("name", name)
    db.save_survivor_state("situation", situation)
    db.save_survivor_state("skills", ",".join(skills))
    db.save_survivor_state("health", health)

    if lang == "zh":
        console.print(f"\n[green]✓ 生存者档案已创建：{name}[/]")
    else:
        console.print(f"\n[green]✓ Survivor profile created: {name}[/]")

    return {"name": name, "situation": situation, "skills": skills, "health": health}


def _step_personality_init(db: Database) -> str:
    lang = get_language()
    step_label = "步骤 5/5：人格初始化" if lang == "zh" else "Step 5/5: Personality Init"
    console.print(f"\n[bold cyan]━━ {step_label} ━━[/]")

    if lang == "zh":
        console.print("火种会根据你的处境自动选择交互风格：")
        console.print("  🔴 危机模式 — 资源紧张或生命受威胁时，简短指令式")
        console.print("  🟡 稳定模式 — 基本需求满足，解释型、鼓励式")
        console.print("  🟢 陪伴模式 — 长期独处时，温暖对话式")
        console.print("  👥 多人模式 — 检测到多人时，中立权威式")
        console.print("  🟣 复兴模式 — 生存稳定后，教师探索式")
        console.print("\n[dim]你无需手动选择，火种会自动切换。[/]")
    else:
        console.print("AllSpark auto-selects interaction style based on your situation:")
        console.print("  🔴 Crisis — When resources low or life threatened, brief & directive")
        console.print("  🟡 Stable — Basic needs met, explanatory & encouraging")
        console.print("  🟢 Companion — Prolonged solitude, warm & conversational")
        console.print("  👥 Multiplayer — Multiple survivors, neutral & authoritative")
        console.print("  🟣 Renaissance — Survival secured, teacher & explorer")
        console.print("\n[dim]No manual selection needed — AllSpark switches automatically.[/]")

    return "auto"


def _step_summary(result: dict):
    lang = get_language()
    profile = result.get("hardware", {}).get("profile")
    flags = result.get("hardware", {}).get("flags")
    survivor = result.get("survivor", {})
    model_result = result.get("model", {})

    if lang == "zh":
        table = Table(title="🔥 初始化摘要", show_header=True, header_style="bold")
        table.add_column("项目", style="cyan")
        table.add_column("设置")
        table.add_row("生存者", survivor.get("name", "—"))
        table.add_row("语言", "中文")
        table.add_row("配置等级", profile.tier.value if profile else "—")
        model_name = flags.llm_model if flags else "—"
        model_status = "✅ 已下载" if model_result.get("downloaded") else "⬇️ 未下载"
        table.add_row("LLM 模型", f"{model_name} ({model_status})")
        table.add_row("交互人格", "自动切换")
    else:
        table = Table(title="🔥 Init Summary", show_header=True, header_style="bold")
        table.add_column("Item", style="cyan")
        table.add_column("Setting")
        table.add_row("Survivor", survivor.get("name", "—"))
        table.add_row("Language", "English")
        table.add_row("Hardware Tier", profile.tier.value if profile else "—")
        model_name = flags.llm_model if flags else "—"
        model_status = "✅ Downloaded" if model_result.get("downloaded") else "⬇️ Not downloaded"
        table.add_row("LLM Model", f"{model_name} ({model_status})")
        table.add_row("Personality", "Auto-switch")

    console.print("\n")
    console.print(table)
