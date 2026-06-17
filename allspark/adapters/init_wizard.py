import locale
import urllib.request
from pathlib import Path

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, DownloadColumn, Progress, TimeRemainingColumn, TransferSpeedColumn
from rich.table import Table
from rich.text import Text

from allspark.core.config import DEFAULT_DB_DIR
from allspark.core.database import Database
from allspark.core.i18n import get_language, set_language, t
from allspark.infrastructure.hardware import (
    LLM_MODEL_MAP,
    HardwareTier,
    compute_feature_flags,
    detect_hardware,
    format_hardware_report,
)
from allspark.infrastructure.module_loader import ModuleRegistry

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

# Mirror sources for regions with limited HuggingFace access
MIRROR_URLS = {
    "Qwen2.5-1.5B-Q4": "https://hf-mirror.com/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
    "Qwen2.5-3B-Q4": "https://hf-mirror.com/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf",
    "Qwen2.5-7B-Q4": "https://hf-mirror.com/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/qwen2.5-7b-instruct-q4_k_m.gguf",
    "Qwen2.5-14B-Q4": "https://hf-mirror.com/Qwen/Qwen2.5-14B-Instruct-GGUF/resolve/main/qwen2.5-14b-instruct-q4_k_m.gguf",
    "Qwen2.5-32B-Q4": "https://hf-mirror.com/Qwen/Qwen2.5-32B-Instruct-GGUF/resolve/main/qwen2.5-32b-instruct-q4_k_m.gguf",
    "Qwen2.5-72B-Q4": "https://hf-mirror.com/Qwen/Qwen2.5-72B-Instruct-GGUF/resolve/main/qwen2.5-72b-instruct-q4_k_m.gguf",
}


def run_init_wizard(db: Database) -> dict:
    console.print(Panel(
        Text.assemble(
            (t("init_welcome_line1") + "\n", "bold red"),
            (t("init_welcome_line2") + "\n", "dim"),
            ("━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n", "dim"),
            (t("init_welcome_line3") + "\n", "white"),
            (t("init_welcome_line4") + "\n", "dim"),
        ),
        title=t("init_title"),
        border_style="red",
        padding=(1, 2)
    ))

    result = {}

    result["language"] = _step_language_select()

    result["hardware"] = _step_hardware_detect(db)
    result["model"] = _step_model_setup(db, result["hardware"])
    result["survivor"] = _step_survivor_profile(db)

    _step_summary(result)

    db.mark_initialized()

    console.print(f"\n[bold green]{t('init_complete_msg')}[/]")
    console.print(f"[dim]{t('init_complete_hint')}[/]\n")

    return result


def _step_hardware_detect(db: Database) -> dict:
    console.print(f"\n[bold cyan]━━ {t('init_step_hardware')} ━━[/]")
    console.print(f"[dim]{t('init_hw_detecting')}[/]\n")

    profile = detect_hardware()
    flags = compute_feature_flags(profile.tier, profile.gpu_available)

    report = format_hardware_report(profile, flags, lang=get_language())
    console.print(report)

    if profile.tier == HardwareTier.PHANTOM:
        console.print(f"\n[yellow]{t('init_hw_below_min')}[/]")
        console.print(f"[dim]{t('init_hw_below_min_hint')}[/]")

    selected_tier = _ask_tier_override(profile.tier)
    if selected_tier != profile.tier:
        profile.tier = selected_tier
        flags = compute_feature_flags(selected_tier, profile.gpu_available)
        tier_names = {
            HardwareTier.PHANTOM: "Phantom (2GB)", HardwareTier.MINIMUM: "Minimum (4GB)",
            HardwareTier.RECOMMENDED: "Recommended (8GB)", HardwareTier.COMFORTABLE: "Comfortable (16GB)",
            HardwareTier.FLAGSHIP: "Flagship (32GB+)",
        }
        tier_name = tier_names.get(selected_tier, selected_tier.value)
        console.print(f"\n[green]{t('init_hw_tier_selected', tier=tier_name)}[/]")
        updated_report = format_hardware_report(profile, flags, lang=get_language())
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


def _ask_tier_override(detected_tier: HardwareTier) -> HardwareTier:
    tier_order = [
        HardwareTier.PHANTOM, HardwareTier.MINIMUM, HardwareTier.RECOMMENDED,
        HardwareTier.COMFORTABLE, HardwareTier.FLAGSHIP,
    ]
    detected_idx = tier_order.index(detected_tier)
    if detected_idx == 0:
        return detected_tier

    tier_names = {
        HardwareTier.PHANTOM: "Phantom (2GB)", HardwareTier.MINIMUM: "Minimum (4GB)",
        HardwareTier.RECOMMENDED: "Recommended (8GB)", HardwareTier.COMFORTABLE: "Comfortable (16GB)",
        HardwareTier.FLAGSHIP: "Flagship (32GB+)",
    }

    console.print(f"\n[dim]{t('init_hw_tier_detected', tier=tier_names[detected_tier])}[/]")
    console.print(f"[dim]{t('init_hw_tier_hint')}[/]")
    console.print(t("init_hw_choose_tier"))

    for i, tier in enumerate(tier_order):
        if i <= detected_idx:
            marker = " ←" if tier == detected_tier else ""
            console.print(f"  {i + 1}. {tier_names[tier]}{marker}")

    console.print(f"  0. {t('init_hw_keep_auto')}")

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
        console.print(f"[red]{t('init_hw_invalid_choice')}[/]")


def _step_language_select() -> str:
    console.print(f"\n[bold cyan]━━ {t('init_step_language')} ━━[/]")
    console.print(t("init_lang_prompt"))

    # SHA-12: detect system locale to suggest a default; user can override.
    try:
        sys_lang = (locale.getlocale()[0] or "").lower()
    except Exception:
        sys_lang = ""
    default_choice = "1" if ("zh" in sys_lang or "cn" in sys_lang or "chinese" in sys_lang) else "2"
    zh_marker = " (default)" if default_choice == "1" else ""
    en_marker = " (default)" if default_choice == "2" else ""

    console.print(f"  1. {t('init_lang_zh')}{zh_marker}")
    console.print(f"  2. {t('init_lang_en')}{en_marker}")

    while True:
        choice = console.input(f"\n🔥 [1/2] (default {default_choice}) > ").strip() or default_choice
        if choice in ("1", "zh"):
            set_language("zh")
            console.print(f"[green]{t('init_lang_set_zh')}[/]")
            return "zh"
        elif choice in ("2", "en", "english"):
            set_language("en")
            console.print(f"[green]{t('init_lang_set_en')}[/]")
            return "en"
        else:
            console.print(f"[red]{t('init_lang_invalid')}[/]")


def _step_model_setup(db: Database, hw_result: dict) -> dict:
    console.print(f"\n[bold cyan]━━ {t('init_step_model')} ━━[/]")

    flags = hw_result.get("flags")
    profile = hw_result.get("profile")
    if not flags or not profile:
        return {"model": None, "downloaded": False}

    recommended = flags.llm_model
    model_info = LLM_MODEL_MAP.get(profile.tier, {})
    size_gb = model_info.get("size_gb", 0)
    speed = model_info.get("speed_tps", "?")

    console.print(t("init_model_recommend", tier=profile.tier.value, model=recommended))
    console.print(t("init_model_size_speed", size=size_gb, speed=speed))

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    existing = list(MODELS_DIR.glob("*.gguf"))

    if existing:
        console.print(f"\n[green]{t('init_model_found', count=len(existing))}[/]")
        for f in existing:
            size_mb = f.stat().st_size / (1024 * 1024)
            console.print(f"  [dim]• {f.name} ({size_mb:.0f} MB)[/]")

    model_downloaded = any(
        recommended.lower().replace("-", "").replace(".", "") in f.stem.lower().replace("-", "").replace(".", "")
        for f in existing
    )

    if model_downloaded:
        console.print(f"\n[green]{t('init_model_ready', model=recommended)}[/]")
        return {"model": recommended, "downloaded": True}

    if not flags.llm:
        console.print(f"\n[yellow]{t('init_model_no_llm')}[/]")
        console.print(f"[dim]{t('init_model_no_llm_hint')}[/]")
        return {"model": None, "downloaded": False}

    console.print(f"\n[yellow]{t('init_model_not_downloaded')}[/]")
    console.print(t("init_model_choose_action"))
    console.print(f"  1. {t('init_model_download', model=recommended, size=size_gb)}")
    console.print(f"  2. {t('init_model_skip')}")
    console.print(f"  3. {t('init_model_other')}")

    while True:
        choice = console.input("\n🔥 [1/2/3] > ").strip()
        if choice == "1":
            _download_model(recommended, size_gb)
            return {"model": recommended, "downloaded": True}
        elif choice == "2":
            console.print(f"[dim]{t('init_model_skip_hint')}[/]")
            return {"model": recommended, "downloaded": False}
        elif choice == "3":
            return _choose_other_model()
        else:
            console.print(f"[red]{t('init_model_invalid_choice')}[/]")


def _choose_other_model() -> dict:
    console.print(f"\n{t('init_model_available')}")

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
        choice = console.input(f"\n🔥 [1-{len(model_keys)}] > ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(model_keys):
                name = model_keys[idx]
                info = LLM_MODEL_MAP.get(
                    next((t for t in HardwareTier if LLM_MODEL_MAP.get(t, {}).get("model") == name), None),
                    {}
                )
                size_gb = info.get("size_gb", 2)
                _download_model(name, size_gb)
                return {"model": name, "downloaded": True}
        except ValueError:
            pass
        console.print(f"[red]{t('init_hw_invalid_choice')}[/]")


def _download_model(model_name: str, size_gb: float):
    url = MODEL_DOWNLOAD_URLS.get(model_name)
    mirror_url = MIRROR_URLS.get(model_name)
    if not url:
        return

    filename = url.split("/")[-1]
    dest = MODELS_DIR / filename

    if dest.exists():
        console.print(f"[green]{t('init_model_exists', path=dest)}[/]")
        return

    console.print(f"\n{t('init_model_downloading', model=model_name)}")
    console.print(f"[dim]{t('init_model_save_to', path=dest)}[/]")
    console.print(f"[dim]{t('init_model_download_hint')}[/]\n")

    # Try primary URL first, then mirror
    urls_to_try = [url]
    if mirror_url and mirror_url != url:
        urls_to_try.append(mirror_url)

    for i, try_url in enumerate(urls_to_try):
        if i > 0:
            console.print(f"\n[yellow]{t('init_model_download_retry')}[/]\n")

        tmp = dest.with_suffix(".tmp")
        try:
            import ssl
            ctx = ssl.create_default_context()
            req = urllib.request.Request(try_url, headers={"User-Agent": "AllSpark/0.2.0"})

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

                with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                    total_size = int(resp.headers.get("Content-Length", 0))
                    progress.update(task, total=total_size)
                    downloaded = 0
                    with open(str(tmp), "wb") as f:
                        while True:
                            chunk = resp.read(8192)
                            if not chunk:
                                break
                            f.write(chunk)
                            downloaded += len(chunk)
                            progress.update(task, completed=downloaded)

            tmp.rename(dest)
            console.print(f"\n[bold green]{t('init_model_download_done', path=dest)}[/]")
            return
        except Exception as e:
            if tmp.exists():
                tmp.unlink()
            console.print(f"\n[red]{t('init_model_download_fail', error=e)}[/]")
            continue

    # All sources failed
    console.print(f"\n[red]{t('init_model_download_all_fail')}[/]")
    console.print(f"[dim]{t('init_model_download_manual_hint')}[/]")


def _step_survivor_profile(db: Database) -> dict:
    console.print(f"\n[bold cyan]━━ {t('init_step_profile')} ━━[/]")
    console.print(f"[dim]{t('init_profile_intro')}[/]\n")

    # Load structured questionnaire data
    questionnaire = _load_questionnaire()

    # --- Section A: Basic Info (required) ---
    console.print(f"[bold]{t('init_section_basic')}[/]")
    name = console.input(f"{t('init_name_label')}: ").strip() or t("init_default_name")
    people_count = console.input(f"{t('init_people_count_label')}: ").strip() or "1"
    is_solo = people_count.strip() in ("1", "")

    # --- Section B: Location (structured selection) ---
    console.print(f"\n[bold]{t('init_section_location')}[/]")
    loc_type = _select_option(
        t("init_loc_type_label"), questionnaire.get("location_types", []), allow_skip=True
    )
    shelter_status = _select_option(
        t("init_shelter_label"), questionnaire.get("shelter_statuses", []), allow_skip=True
    )
    gps_input = console.input(f"{t('init_gps_label')}: ").strip()

    # --- Section C: Health (structured) ---
    health = _select_option(
        t("init_health_label"), questionnaire.get("health_statuses", []), allow_skip=True
    ) or "unknown"
    others_str = ""
    group_health = ""
    if not is_solo:
        others_str = console.input(f"{t('init_others_label')}: ").strip()
        group_health = console.input(f"{t('init_group_health_label')}: ").strip()

    # --- Section D: Supplies (optional) ---
    console.print(f"\n[bold]{t('init_section_supplies')}[/]")
    supplies_answer = console.input(f"{t('init_supplies_prompt')} ").strip().lower()

    water = ""
    food = ""
    power = ""
    tools_str = ""

    if supplies_answer in (t("init_yes").lower(), "y", "yes"):
        water = console.input(f"{t('init_water_label')}: ").strip()
        food = console.input(f"{t('init_food_label')}: ").strip()
        power = console.input(f"{t('init_power_label')}: ").strip()
        tools_str = console.input(f"{t('init_tools_label')}: ").strip()

    tools = [s.strip() for s in tools_str.split(",") if s.strip()]

    # --- Section E: Threats & Skills (structured multi-select) ---
    console.print(f"\n[bold]{t('init_section_threats')}[/]")
    threats = _select_multi(
        t("init_threats_label"), questionnaire.get("threat_types", []), allow_skip=True
    )
    urgency = _select_option(
        t("init_urgency_label"), questionnaire.get("urgency_levels", []), allow_skip=True
    )
    skills = _select_multi(
        t("init_skills_label"), questionnaire.get("skill_categories", []), allow_skip=True
    )

    # --- Save to DB ---
    db.save_survivor_state("name", name)
    db.save_survivor_state("location_type", loc_type)
    db.save_survivor_state("shelter", shelter_status)
    db.save_survivor_state("gps_input", gps_input)
    db.save_survivor_state("people_count", people_count)
    db.save_survivor_state("others", others_str)
    db.save_survivor_state("health", health)
    db.save_survivor_state("group_health", group_health)
    db.save_survivor_state("water", water)
    db.save_survivor_state("food", food)
    db.save_survivor_state("power", power)
    db.save_survivor_state("tools", ",".join(tools))
    db.save_survivor_state("skills", ",".join(skills))
    db.save_survivor_state("threats", ",".join(threats))
    db.save_survivor_state("urgency", urgency)
    db.save_survivor_state("questionnaire_version", "2")

    console.print(f"\n[green]{t('init_profile_created', name=name)}[/]")
    console.print(f"[dim]{t('init_profile_hint')}[/]")

    return {
        "name": name,
        "location_type": loc_type,
        "shelter": shelter_status,
        "gps_input": gps_input,
        "people_count": people_count,
        "health": health,
        "group_health": group_health,
        "water": water,
        "food": food,
        "power": power,
        "tools": tools,
        "skills": skills,
        "threats": threats,
        "urgency": urgency,
    }


def _load_questionnaire() -> dict:
    """Load structured questionnaire data from YAML."""
    q_path = Path(__file__).resolve().parent / "data" / "questionnaire.yaml"
    if not q_path.exists():
        return {}
    with open(q_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _select_option(prompt_text: str, options: list, *, allow_skip: bool = False) -> str:
    """Display numbered options and return selected key. Free text input via '0'."""
    if not options:
        return console.input(f"{prompt_text}: ").strip()

    for i, opt in enumerate(options, 1):
        label = t(opt["label_key"])
        console.print(f"  {i}. {label}")
    if allow_skip:
        console.print(f"  0. {t('q_custom_or_skip')}")

    while True:
        choice = console.input(f"\n🔥 {prompt_text} [{1}-{len(options)}{'/0' if allow_skip else ''}] > ").strip()
        if choice == "0" and allow_skip:
            custom = console.input(f"  {t('q_enter_custom')}: ").strip()
            return custom
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                selected = options[idx]
                console.print(f"  [green]✓ {t(selected['label_key'])}[/]")
                return selected["key"]
        except ValueError:
            pass
        console.print(f"[red]{t('q_invalid_choice')}[/]")


def _select_multi(prompt_text: str, options: list, *, allow_skip: bool = False) -> list[str]:
    """Display numbered options for multi-select. Returns list of selected keys."""
    if not options:
        raw = console.input(f"{prompt_text} ({t('q_comma_separated')}): ").strip()
        return [s.strip() for s in raw.split(",") if s.strip()]

    for i, opt in enumerate(options, 1):
        label = t(opt["label_key"])
        console.print(f"  {i}. {label}")
    if allow_skip:
        console.print(f"  0. {t('q_custom_or_skip')}")

    hint = t("q_multi_hint", count=len(options))
    choice = console.input(f"\n🔥 {prompt_text} {hint} > ").strip()

    if not choice:
        return []

    selected = []
    for part in choice.split(","):
        part = part.strip()
        if part == "0" and allow_skip:
            custom = console.input(f"  {t('q_enter_custom')}: ").strip()
            if custom:
                selected.append(custom)
        else:
            try:
                idx = int(part) - 1
                if 0 <= idx < len(options):
                    key = options[idx]["key"]
                    if key not in selected:
                        selected.append(key)
                        console.print(f"  [green]✓ {t(options[idx]['label_key'])}[/]")
            except ValueError:
                # Accept free text
                if part:
                    selected.append(part)

    return selected


def _step_summary(result: dict):
    profile = result.get("hardware", {}).get("profile")
    flags = result.get("hardware", {}).get("flags")
    survivor = result.get("survivor", {})
    model_result = result.get("model", {})

    table = Table(title=t("init_summary_title"), show_header=True, header_style="bold")
    table.add_column(t("init_summary_col_item"), style="cyan")
    table.add_column(t("init_summary_col_setting"))

    lang = get_language()
    lang_display = t("init_summary_language_zh") if lang == "zh" else t("init_summary_language_en")

    table.add_row(t("init_summary_survivor"), survivor.get("name", "—"))
    table.add_row(t("init_summary_language"), lang_display)
    table.add_row(t("init_summary_tier"), profile.tier.value if profile else "—")

    model_name = flags.llm_model if flags else "—"
    model_status = t("init_summary_model_downloaded") if model_result.get("downloaded") else t("init_summary_model_not_downloaded")
    table.add_row(t("init_summary_model"), f"{model_name} ({model_status})")
    table.add_row(t("init_summary_personality"), t("init_summary_auto"))

    console.print("\n")
    console.print(table)
