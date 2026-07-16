import locale
import urllib.request
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, DownloadColumn, Progress, TimeRemainingColumn, TransferSpeedColumn
from rich.table import Table
from rich.text import Text

from allspark.core.config import DEFAULT_DB_DIR
from allspark.core.database import Database
from allspark.core.i18n import get_language, set_language, t
from allspark.core.models import RESOURCE_UNITS, ResourceType
from allspark.infrastructure.hardware import (
    DeployMode,
    HardwareTier,
    compute_feature_flags,
    detect_hardware,
    format_hardware_report,
    resolve_runtime_deploy_mode,
)
from allspark.infrastructure.module_loader import ModuleRegistry
from allspark.services.initial_assessment import (
    InitialAssessmentValidationError,
    assessment_preview,
    validate_initial_assessment,
)
from allspark.services.resource_manager import ResourceManager, ResourceValidationError
from allspark.services.survival_plan import SurvivalPlanService

console = Console()

MODELS_DIR = DEFAULT_DB_DIR / "models"

# Model URLs and metadata live in allspark/data/models.yaml.
# Use model_registry to access them.
from allspark.services import model_registry as _registry  # noqa: E402


def _detect_initial_language() -> str:
    """Choose a deterministic display language before first-run confirmation."""
    try:
        sys_lang = (locale.getlocale()[0] or "").lower()
    except Exception:
        sys_lang = ""
    return "zh" if any(token in sys_lang for token in ("zh", "cn", "chinese")) else "en"


def run_init_wizard(db: Database) -> dict:
    # This only controls the pre-choice display. The adapter persists language
    # together with the initialized marker after runtime preparation succeeds.
    set_language(_detect_initial_language(), persist=False)
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

    result: dict[str, Any] = {}

    result["language"] = _step_language_select()

    while True:
        result["assessment"] = _step_initial_assessment()
        if _step_assessment_summary(result["assessment"]):
            break

    plan_service = SurvivalPlanService(db, ResourceManager(db))
    plan = plan_service.generate(result["assessment"])
    result["plan_id"] = plan.id
    result["primary_action_id"] = _step_plan_selection(
        plan_service.payload(plan)
    )

    # Hardware is supporting runtime context, never another interactive gate.
    # Tier override, model, GPS, skills, and profile details belong to advanced
    # settings after the first useful assessment is published.
    result["hardware"] = _prepare_hardware_automatically(db)

    return result


def _step_plan_selection(plan: dict[str, Any]) -> str:
    """Show the first 24-hour plan and require one explicit primary action."""
    console.print(f"\n[bold cyan]━━ {t('survival_plan_heading')} ━━[/]")
    console.print(f"[dim]{plan['phase_description']}[/]")
    primary_ids = set(plan["primary_candidate_ids"])
    candidates = [
        action for action in plan["actions"] if action["id"] in primary_ids
    ]
    for index, action in enumerate(candidates, 1):
        console.print(f"  {index}. [bold]{action['title']}[/]")
        console.print(f"     {t('survival_plan_why_label')}: {action['why_now_text']}")
        console.print(
            f"     {t('survival_plan_prerequisite_label')}: "
            + "; ".join(action["prerequisite_texts"])
        )
        console.print(f"     {t('survival_plan_done_label')}: {action['done_when_text']}")
        console.print(f"     {t('web_init_plan_risk_label')}: {action['risk_text']}")
        console.print(f"     {t('web_primary_plan_reassess')}: {action['reassess_at_text']}")
    later_actions = [
        action for action in plan["actions"] if action["id"] not in primary_ids
    ]
    if later_actions:
        console.print(f"\n[bold]{t('web_init_plan_later_actions')}[/]")
        for action in later_actions:
            console.print(f"  - {action['title']} — {action['why_now_text']}")
    while True:
        answer = console.input(
            t("survival_plan_select_prompt", count=len(candidates)) + " > "
        ).strip()
        try:
            selected = int(answer) - 1
        except ValueError:
            selected = -1
        if 0 <= selected < len(candidates):
            return candidates[selected]["id"]
        console.print(f"[red]{t('q_invalid_choice')}[/]")


def _prepare_hardware_automatically(db: Database) -> dict:
    profile = detect_hardware()
    flags = compute_feature_flags(profile.tier, profile.gpu_available)
    _resolve_runtime_flags(db, flags)
    return {"profile": profile, "flags": flags}


def persist_detected_hardware(
    db: Database, hardware: dict, *, commit: bool = True
) -> None:
    """Publish detected hardware only with the initialization transaction."""
    profile = hardware.get("profile")
    flags = hardware.get("flags")
    if profile is None or flags is None:
        return
    for key, value in [
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
        db.save_hardware_profile(key, value, commit=commit)
    ModuleRegistry(flags).save_to_db(db, commit=commit)


def _step_hardware_detect(db: Database) -> dict:
    console.print(f"\n[bold cyan]━━ {t('init_step_hardware')} ━━[/]")
    console.print(f"[dim]{t('init_hw_detecting')}[/]\n")

    profile = detect_hardware()
    flags = compute_feature_flags(profile.tier, profile.gpu_available)
    _resolve_runtime_flags(db, flags)

    registry = ModuleRegistry(flags)
    report = format_hardware_report(
        profile,
        flags,
        lang=get_language(),
        capabilities=registry.format_status_dict(),
    )
    console.print(report)

    if profile.tier == HardwareTier.PHANTOM:
        console.print(f"\n[yellow]{t('init_hw_below_min')}[/]")
        console.print(f"[dim]{t('init_hw_below_min_hint')}[/]")

    selected_tier = _ask_tier_override(profile.tier)
    if selected_tier != profile.tier:
        profile.tier = selected_tier
        flags = compute_feature_flags(selected_tier, profile.gpu_available)
        _resolve_runtime_flags(db, flags)
        registry = ModuleRegistry(flags)
        tier_names = {
            HardwareTier.PHANTOM: "Phantom (2GB)", HardwareTier.MINIMUM: "Minimum (4GB)",
            HardwareTier.RECOMMENDED: "Recommended (8GB)", HardwareTier.COMFORTABLE: "Comfortable (16GB)",
            HardwareTier.FLAGSHIP: "Flagship (32GB+)",
        }
        tier_name = tier_names.get(selected_tier, selected_tier.value)
        console.print(f"\n[green]{t('init_hw_tier_selected', tier=tier_name)}[/]")
        updated_report = format_hardware_report(
            profile,
            flags,
            lang=get_language(),
            capabilities=registry.format_status_dict(),
        )
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

    registry.save_to_db(db)

    return {"profile": profile, "flags": flags}


def _resolve_runtime_flags(db: Database, flags) -> None:
    docker_available = False
    if flags.docker_eligible:
        from allspark.docker_manager import DockerManager

        manager = DockerManager(
            db=db,
            flags=flags,
            deploy_mode=DeployMode(flags.recommended_deploy_mode),
        )
        docker_available = manager.is_docker_available()
    resolve_runtime_deploy_mode(flags, docker_available)


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
    initial_language = _detect_initial_language()
    set_language(initial_language, persist=False)
    console.print(f"\n[bold cyan]━━ {t('init_step_language')} ━━[/]")
    console.print(t("init_lang_prompt"))
    console.print(f"[dim]{t('init_lang_switch_hint')}[/]")

    default_choice = "1" if initial_language == "zh" else "2"
    zh_marker = " (default)" if default_choice == "1" else ""
    en_marker = " (default)" if default_choice == "2" else ""

    console.print(f"  1. {t('init_lang_zh')}{zh_marker}")
    console.print(f"  2. {t('init_lang_en')}{en_marker}")

    while True:
        choice = console.input(f"\n🔥 [1/2] (default {default_choice}) > ").strip() or default_choice
        if choice in ("1", "zh"):
            set_language("zh", persist=False)
            console.print(f"[green]{t('init_lang_set_zh')}[/]")
            return "zh"
        elif choice in ("2", "en", "english"):
            set_language("en", persist=False)
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
    try:
        recommended_entry = _registry.get_model(recommended)
        size_gb = recommended_entry.file_gb
        speed = recommended_entry.speed_tps
    except KeyError:
        # Recommended model isn't in the catalog (user override pointing
        # at a custom .gguf). Show placeholders.
        size_gb = 0
        speed = "?"

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

    catalog = _registry.list_models()
    for i, entry in enumerate(catalog, 1):
        console.print(
            f"  {i}. {entry.name} (~{entry.file_gb}GB, ~{entry.speed_tps} t/s, "
            f"min {entry.min_ram_gb}GB RAM)"
        )

    while True:
        choice = console.input(f"\n🔥 [1-{len(catalog)}] > ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(catalog):
                entry = catalog[idx]
                _download_model(entry.name, entry.file_gb)
                return {"model": entry.name, "downloaded": True}
        except ValueError:
            pass
        console.print(f"[red]{t('init_hw_invalid_choice')}[/]")


def _download_model(model_name: str, size_gb: float):
    try:
        entry = _registry.get_model(model_name)
        url = entry.url_hf
        mirror_url = entry.url_mirror
    except KeyError:
        # Unknown model name (probably a user-supplied custom .gguf already
        # placed in MODELS_DIR) — nothing to download.
        return
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


def _explicit_known_state(label: str) -> str:
    while True:
        console.print(f"\n[bold]{label}[/]")
        console.print(f"  1. {t('init_assessment_known')}")
        console.print(f"  2. {t('init_assessment_unknown')}")
        choice = console.input("🔥 [1/2] > ").strip()
        if choice == "1":
            return "known"
        if choice == "2":
            return "unknown"
        console.print(f"[red]{t('init_assessment_explicit_required')}[/]")


def _required_fact(label: str, options: list[dict]) -> dict[str, Any]:
    while True:
        console.print(f"\n[bold]{label}[/]")
        for index, option in enumerate(options, 1):
            console.print(f"  {index}. {t(option['label_key'])}")
        unknown_index = len(options) + 1
        console.print(f"  {unknown_index}. {t('init_assessment_unknown')}")
        choice = console.input(f"🔥 [1-{unknown_index}] > ").strip()
        try:
            index = int(choice) - 1
        except ValueError:
            index = -1
        if 0 <= index < len(options):
            return {"status": "known", "value": options[index]["key"]}
        if index == len(options):
            return {"status": "unknown"}
        console.print(f"[red]{t('init_assessment_explicit_required')}[/]")


def _required_threats(options: list[dict]) -> dict[str, Any]:
    while True:
        console.print(f"\n[bold]{t('init_threats_label')}[/]")
        console.print(f"  1. {t('init_assessment_threat_none')}")
        console.print(f"  2. {t('init_assessment_threat_selected')}")
        console.print(f"  3. {t('init_assessment_unknown')}")
        state = console.input("🔥 [1/2/3] > ").strip()
        if state == "1":
            return {"status": "none", "values": []}
        if state == "3":
            return {"status": "unknown", "values": []}
        if state != "2":
            console.print(f"[red]{t('init_assessment_explicit_required')}[/]")
            continue
        for index, option in enumerate(options, 1):
            console.print(f"  {index}. {t(option['label_key'])}")
        raw = console.input(t("init_assessment_threat_prompt") + " > ").strip()
        try:
            indexes = [int(part.strip()) - 1 for part in raw.split(",")]
        except ValueError:
            indexes = []
        if indexes and all(0 <= index < len(options) for index in indexes):
            values = list(dict.fromkeys(options[index]["key"] for index in indexes))
            return {"status": "selected", "values": values}
        console.print(f"[red]{t('init_assessment_threat_required')}[/]")


def _resource_assessment(resource_type: ResourceType) -> dict:
    label = t(f"resource_{resource_type.value}")
    amount_status = _explicit_known_state(
        t("init_assessment_resource_amount", resource=label)
    )
    amount = None
    confirm_outlier = False
    if amount_status == "known":
        while True:
            raw = console.input(
                t(
                    "init_assessment_resource_value",
                    resource=label,
                    unit=RESOURCE_UNITS[resource_type],
                )
                + " > "
            ).strip()
            try:
                amount = ResourceManager.validate_value("amount", raw)
            except ResourceValidationError as exc:
                console.print(f"[red]{t(f'error_resource_{exc.reason}', field=label)}[/]")
                continue
            if amount > ResourceManager.RESOURCE_SOFT_MAX[resource_type]:
                confirm = console.input(t("init_assessment_outlier_confirm") + " [y/n] > ").strip().lower()
                if confirm not in {"y", "yes", "是"}:
                    continue
                confirm_outlier = True
            break

    rates: dict[str, Any]
    while True:
        console.print(t("init_assessment_rate_state", resource=label))
        console.print(f"  1. {t('init_assessment_rate_unknown')}")
        console.print(f"  2. {t('init_assessment_rate_estimate')}")
        rate_choice = console.input("🔥 [1/2] > ").strip()
        if rate_choice == "1":
            rates = {"status": "unknown"}
            break
        if rate_choice != "2":
            console.print(f"[red]{t('init_assessment_explicit_required')}[/]")
            continue
        try:
            consumption = ResourceManager.validate_value(
                "daily_consumption",
                console.input(
                    f"{t('init_assessment_daily_consumption')} "
                    f"({t(f'resource_unit_{resource_type.value}')}/{t('web_init_day_short')}) > "
                ).strip(),
            )
            intake = ResourceManager.validate_value(
                "daily_intake",
                console.input(
                    f"{t('init_assessment_daily_intake')} "
                    f"({t(f'resource_unit_{resource_type.value}')}/{t('web_init_day_short')}) > "
                ).strip(),
            )
        except ResourceValidationError as exc:
            console.print(f"[red]{t(f'error_resource_{exc.reason}', field=label)}[/]")
            continue
        rates = {
            "status": "estimate",
            "basis": "group_total",
            "daily_consumption": consumption,
            "daily_intake": intake,
        }
        if max(consumption, intake) > ResourceManager.RESOURCE_SOFT_MAX[resource_type]:
            confirm = console.input(t("init_assessment_outlier_confirm") + " [y/n] > ").strip().lower()
            if confirm not in {"y", "yes", "是"}:
                continue
            confirm_outlier = True
        break

    result = {
        "status": amount_status,
        "rates": rates,
        "confirm_outlier": confirm_outlier,
    }
    if amount_status == "known":
        result["amount"] = amount
    return result


def _step_initial_assessment() -> dict:
    console.print(f"\n[bold cyan]━━ {t('init_step_assessment')} ━━[/]")
    console.print(f"[dim]{t('init_assessment_intro')}[/]")
    questionnaire = _load_questionnaire()
    people_status = _explicit_known_state(t("init_people_count_label"))
    people: dict[str, Any] = {"status": people_status}
    if people_status == "known":
        while True:
            raw = console.input(t("init_assessment_people_value") + " > ").strip()
            try:
                people["value"] = ResourceManager.validate_people_count(raw)
                break
            except ResourceValidationError as exc:
                console.print(f"[red]{t(f'error_resource_{exc.reason}', field=t('assessment_field_people_count'))}[/]")

    assessment = {
        "people_count": people,
        "health": _required_fact(
            t("init_health_label"), questionnaire.get("health_statuses", [])
        ),
        "urgency": _required_fact(
            t("init_urgency_label"), questionnaire.get("urgency_levels", [])
        ),
        "shelter": _required_fact(
            t("init_shelter_label"), questionnaire.get("shelter_statuses", [])
        ),
        "threats": _required_threats(questionnaire.get("threat_types", [])),
        "resources": {},
        "confirmed": True,
    }
    assessment["resources"] = {
        resource_type.value: _resource_assessment(resource_type)
        for resource_type in ResourceType
    }
    try:
        return validate_initial_assessment(assessment)
    except InitialAssessmentValidationError as exc:
        raise RuntimeError("CLI produced an invalid initial assessment") from exc


def _step_assessment_summary(assessment: dict) -> bool:
    preview = assessment_preview(assessment)
    console.print(f"\n[bold cyan]━━ {t('init_assessment_summary_title')} ━━[/]")
    console.print(f"[bold]{t('init_assessment_known_facts')}[/]")
    for fact in preview["known"]:
        value = fact["value"]
        if isinstance(value, list):
            value = ", ".join(value) or t("init_assessment_threat_none")
        if fact.get("unit"):
            value = f"{value} {fact['unit']}"
        label = t(f"assessment_field_{fact['domain']}")
        console.print(f"  ✓ {label}: {value}")
    console.print(f"[bold]{t('init_assessment_unknown_facts')}[/]")
    for domain in preview["unknown"]:
        base = domain[:-5] if domain.endswith("_rate") else domain
        suffix = t("init_assessment_rate_suffix") if domain.endswith("_rate") else ""
        console.print(f"  ◇ {t(f'assessment_field_{base}')}{suffix}")
    console.print(f"[bold]{t('web_init_summary_resources')}[/]")
    for resource in preview["resources"]:
        label = t(f"assessment_field_{resource['domain']}")
        unit = t(f"resource_unit_{resource['domain']}")
        amount = (
            f"{resource['amount']} {unit}"
            if resource["amount_status"] == "known"
            else t("init_assessment_unknown")
        )
        if resource["rate_status"] == "estimate":
            source = t(f"resource_source_{resource['source']}")
            rate = t("web_init_rate_summary").format(
                consumption=(
                    f"{resource['daily_consumption']} {unit}/{t('web_init_day_short')}"
                ),
                intake=(
                    f"{resource['daily_intake']} {unit}/{t('web_init_day_short')}"
                ),
                source=source,
            )
            rate = f"{rate} · {t('web_init_group_total_basis')}"
        else:
            rate = t("init_assessment_rate_unknown")
        console.print(f"  • {label}: {amount}; {rate}; {preview['as_of']}")
    while True:
        answer = console.input(t("init_assessment_confirm") + " [y/n] > ").strip().lower()
        if answer in {"y", "yes", "是"}:
            return True
        if answer in {"n", "no", "否"}:
            return False
        console.print(f"[red]{t('init_assessment_explicit_required')}[/]")


def _step_optional_profile() -> dict:
    console.print(f"\n[bold]{t('init_assessment_optional_title')}[/]")
    name = console.input(f"{t('init_name_label')}: ").strip() or t("init_default_name")
    gps_input = console.input(f"{t('init_gps_label')}: ").strip()
    skills_raw = console.input(f"{t('init_skills_label')}: ").strip()
    return {
        "name": name,
        "gps_input": gps_input,
        "skills": [value.strip() for value in skills_raw.split(",") if value.strip()],
    }


def _load_questionnaire() -> dict:
    """Load structured questionnaire data from YAML.

    The questionnaire lives at ``allspark/data/questionnaire.yaml`` (a packaged
    data asset), not next to this module under ``adapters/data/`` — the old
    path silently fell through to ``{}`` and the CLI degraded to free-text
    (SHA-56).
    """
    q_path = Path(__file__).resolve().parent.parent / "data" / "questionnaire.yaml"
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
