"""CLI regression — feed every CLI command through `python -m allspark`.

Coverage (mapped to PRD §三 modules + commands/ files):
  basic        status, resource, set, lang, exit         (M1, M7, M8)
  knowledge    know, map, exp, task                       (M3)
  goals        goals, reset                               (M10, M11)
  survival     briefing, timeline, diary, weather,
               psychology, gps, env, voice                (M12-16, M14)
  comms        network, vision                            (M6, +vision)
  governance   community, trade                           (M5)
  hardware     power, sensor, preserve                    (+hardware)
  ai           llm, module, skf, verify                   (+modules, +SKF)
  docker       docker                                     (+infra)
  help         help                                       (cosmetic)

NOT covered here (interactive flows, see README §下一轮):
  - init wizard (we pre-seed an initialized DB to skip it)
  - voice commands (require microphone)
  - vision <image> (requires real image + multimodal model)
  - llm chat <message> (requires loaded GGUF)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = "tests.regression"

from tests.regression._harness import (
    REPORTS_DIR,
    CallRecord,
    Recorder,
    cli_drive,
    detect_i18n_leaks,
    render_summary,
    seed_initialized_db,
)

# Commands covering every CLI module in `allspark/commands/`.
COMMAND_SCRIPT = [
    # baseline
    "help",
    "status",
    "resource",
    "tasks",
    # knowledge
    "know water",
    "know 水",
    "know nonexistent_xxx_topic",
    "map",
    "exp recent",
    # goals
    "goals",
    # survival
    "briefing",
    "timeline",
    "diary",
    "weather",
    "psychology",
    "env",
    "gps",
    # comms
    "network",
    "vision",
    # hardware
    "power",
    "sensor",
    "preserve",
    # ai
    "llm",
    "module",
    "skf",
    "verify",
    # governance
    "community",
    "trade",
    # docker
    "docker",
    # i18n switch + re-run a few
    "lang en",
    "status",
    "briefing",
    "help",
    "resource",
    "goals",
    "weather",
    "psychology",
    "lang zh",
    "status",
    # boundary
    "set water foo",
    "set unknown 5",
    "lang klingon",
    "module enable __nope__",
    # exit
    "exit",
]


# Heuristic: words that should NOT appear as plain English in a zh terminal
# (and vice versa). "Phase N" stays — PRD §三.2 keeps `Phase 0..4` as a
# cross-language term of art for survival stages. If you want it
# translated, add a `phase_label_<n>` key and route the renderer through
# t() instead of the bare format string in mission_planner.
_EN_WORDS_IN_ZH_BAD = re.compile(
    r"\b(URGENT|Find safe water|Find food|Active Tasks|Active Goals|"
    r"Loading|Error checking|Failed to|No results|"
    r"Overall: lonely|Overall: stressed)\b"
)


def _flag_segment(text: str, lang: str) -> list[str]:
    """Return flags for a chunk of CLI output rendered under `lang`."""
    flags: list[str] = []
    if "Traceback" in text:
        flags.append("traceback")
    leaks = detect_i18n_leaks(text)
    if leaks:
        flags.append("i18n_leak")
    if lang == "zh":
        if _EN_WORDS_IN_ZH_BAD.search(text):
            flags.append("en_in_zh")
    elif lang == "en":
        # Untranslated zh chars in en mode (excluding seeded test inputs / brand).
        zh_chars = re.findall(r"[一-鿿]+", text)
        zh_chars = [z for z in zh_chars if z not in {"火种"}]
        # SHA-60: the CLI prints the startup banner exactly once, using the
        # *initial* language, before any `lang en` takes effect. That banner
        # therefore bleeds into the first en-segment as the zh app_subtitle.
        # Strip the seeded zh subtitle ("离线人工智能生存系统") so it does not
        # register as a real i18n leak — it is a harness segmentation artifact.
        zh_chars = [z for z in zh_chars if z != "离线人工智能生存系统"]
        if zh_chars:
            flags.append("zh_in_en")
    return flags


_LANG_SWITCH_MARKERS = [
    (re.compile(r"Language switched to English|switched to en\b", re.IGNORECASE), "en"),
    (re.compile(r"语言已切换为\s*中文|switched to zh\b", re.IGNORECASE), "zh"),
]


def _split_by_lang(stdout: str) -> list[tuple[str, str]]:
    """Split CLI output at language-switch confirmations.

    The CLI uses `console.input()` which doesn't echo typed commands, so we
    can't rely on seeing "lang en" in stdout. Instead, we look for the
    confirmation messages emitted *after* a successful lang change.

    Returns [(lang, segment), ...]. Segments before the first switch are
    tagged with the seeded init language ("zh" by default).
    """
    segments: list[tuple[str, str]] = []
    cur_lang = "zh"  # seeded by suite_cli.main()
    buf: list[str] = []
    for line in stdout.splitlines():
        switched_to = None
        for pattern, target in _LANG_SWITCH_MARKERS:
            if pattern.search(line):
                switched_to = target
                break
        if switched_to:
            # SHA-60: the confirmation line is emitted in the *target*
            # language (e.g. "语言已切换为 中文" when switching TO zh), so it
            # belongs to the new segment, not the previous one. Attaching it
            # to the old segment caused the zh confirmation to register as a
            # zh_in_en false positive.
            segments.append((cur_lang, "\n".join(buf)))
            buf = [line]
            cur_lang = switched_to
        else:
            buf.append(line)
    if buf:
        segments.append((cur_lang, "\n".join(buf)))
    return segments


def main() -> int:
    db = REPORTS_DIR / "_cli_session.db"
    if db.exists():
        db.unlink()
    seed_initialized_db(db, language="zh")

    jsonl = REPORTS_DIR / "cli.jsonl"
    recorder = Recorder(jsonl)

    stdout, stderr, rc = cli_drive(db, COMMAND_SCRIPT, timeout=240)

    # 1. One overall record for the whole session.
    overall = CallRecord(
        kind="cli",
        label="cli session",
        request={"commands": len(COMMAND_SCRIPT)},
        response={"rc": rc, "stdout_len": len(stdout), "stderr_len": len(stderr)},
    )
    if rc != 0:
        overall.flags.append("nonzero_rc")
    if "Traceback" in stdout or "Traceback" in stderr:
        overall.flags.append("traceback")
    recorder.add(overall)

    # 2. Per-language segment records carry the leak/cross-lang flags.
    for idx, (lang, segment) in enumerate(_split_by_lang(stdout)):
        rec = CallRecord(
            kind="cli",
            label=f"segment#{idx}",
            lang=lang if lang in {"zh", "en"} else None,
            request={"len": len(segment)},
            response={"snippet": segment[:300]},
        )
        rec.flags.extend(_flag_segment(segment, lang))
        recorder.add(rec)

    # 3. Persist raw artifacts for triage.
    (REPORTS_DIR / "cli_stdout.txt").write_text(stdout)
    (REPORTS_DIR / "cli_stderr.txt").write_text(stderr)

    md = render_summary(recorder.records)
    (REPORTS_DIR / "cli.md").write_text(
        f"# CLI regression — rc={rc}, {len(stdout)}B stdout / {len(stderr)}B stderr\n\n"
        f"Summary: `{recorder.summary()}`\n\n{md}\n"
    )
    recorder.close()

    print(f"\n{recorder.summary()}")
    print(f"\nresults: {jsonl}")
    print(f"summary: {REPORTS_DIR / 'cli.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
