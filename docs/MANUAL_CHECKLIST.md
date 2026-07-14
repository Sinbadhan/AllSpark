# Manual Verification Checklist

> **Purpose:** Cover what the automated `pytest tests/` suite cannot —
> keyboard/screen-reader/zoom usability, live LLM, voice/vision hardware,
> cross-node spark networking, Docker elastic deployment, and long-running
> schedulers. Run before tagging
> any minor or major release; record results in the release PR.
> **Tracks:** SHA-36, SHA-152, SHA-33

CI on GitHub runs `ruff` + `mypy` + the complete tracked `pytest` suite on
Python 3.10/3.11/3.12. The canonical Python 3.10 coverage job feeds
`scripts/check_coverage.py`, which enforces at least 75% total line coverage
plus at least 90% branch coverage on the eight SHA-151 critical-path modules;
every supported version also runs the collection-count floor to prevent silent
test deletion. This checklist covers what automation cannot prove:
assistive-technology and zoom usability, live LLM, voice/vision hardware,
cross-node hardware, Docker deployment, and long-running schedulers.

---

## 1. Release-blocking checks (run for every tag)

| # | Item | How | Pass criteria |
|---:|------|-----|---------------|
| 1.1 | CLI cold start | `python -m allspark` from a fresh `~/.allspark/` | wizard runs to completion in expected language; status panel renders |
| 1.2 | Web UI cold start | `python -m allspark --web` then open `http://localhost:8000` | init wizard appears in browser language; no 500 in `/api/status` |
| 1.3 | i18n round-trip | start zh → switch to en in CLI and Web → switch back | no Chinese in en mode; no English in zh mode (modulo user-typed content) |
| 1.4 | Reset L1/L2/L3 | seed diary/timeline/action-plan/knowledge-vector data; run each level in an isolated DB; restart between accepted and rejected attempts | L2 clears private operational history but keeps knowledge/vector/hardware/language; L3 clears every top-level application table, keeps language, writes one new audit row, and returns to `/`; cooldown survives restart and rejected/forced attempts are attributable |
| 1.5 | SKF export/import round-trip | `skf export ~/Desktop/test.skf` → fresh DB → `skf import ~/Desktop/test.skf` | same knowledge count after import; SHA256 verified |
| 1.6 | Backup auto-snapshot | quit cleanly → check `~/.allspark/backups/` | latest snapshot has `_clean.db` and `_metadata.json` |
| 1.7 | Keyboard-only Web flow | disconnect/ignore the pointer; complete init, mobile navigation, resource edit, Repository filter/detail, and modal close | every control is reachable with visible focus; modal Tab/Shift+Tab trap, Esc close, and trigger-focus restore all work |
| 1.8 | macOS screen reader | run the same core Web flow with VoiceOver on macOS | landmarks, control names, selected/expanded state, validation errors, dialogs, and status changes are announced without duplicate or symbol-only names |
| 1.8W | Windows screen reader (Testing) | run the same core Web flow with NVDA on Windows when that environment is available | record pass/fail evidence; until a real run passes, Windows + NVDA remains Experimental and must not be included in the Stable accessibility claim |
| 1.9 | Browser zoom | set browser zoom to 200% on a 1280px-wide desktop viewport; repeat the core Web flow | no text/control overlap or clipped actions; no page-level horizontal scroll; data tables may use a clearly contained horizontal scroller |
| 1.10 | Environment evidence states | inspect CLI and Web environment assessment with (a) no sensor/resource setup, (b) one stale sensor or partial resources, and (c) fresh climate + terrain + configured power/water/food | (a)/(b) show insufficient evidence, missing dimensions, source/time and no numeric score or exploration advice; known shortages still warn; only (c) emits a score and opportunities |
| 1.11 | Answer trust consistency | on a fresh install, compare `/api/system/health`, the Web footer and one specific plus one broad rule-based question in Web and CLI; repeat after configuring a critical then healthy core resource set | system health wording agrees across surfaces; resource readiness changes independently; broad/no-match/generated answers disclose their scope; degraded or uncertain answers never say “Status Normal” or use a success checkmark |
| 1.12 | Config runtime contract | open `/config` with LLM unloaded, inspect identity/runtime/feature fields, then repeat while each backing API is unavailable | no console or promise errors; normal fields match `/api/system/about`, `/api/system/health`, `/api/llm/status`, `/api/init/hardware`; unavailable sections show localized fallback without blanking successful sections |
| 1.13 | Web first-run language flow | open a fresh database once with a zh browser locale and once with en; switch zh → en → zh while moving forward/back and entering questionnaire values; repeat after L3 reset | language is the first actionable step and follows browser locale; every heading, option, placeholder and error rerenders; entered values survive both switches; every select and skip control has a stable accessible name |

## 2. Hardware-dependent (run when hardware available — SHA-33)

| # | Item | Hardware | Notes |
|---:|------|----------|-------|
| 2.1 | LLM inference | CPU+GPU box with `llama-cpp-python` and the tier-default Qwen3 GGUF | first response within 60 s; subsequent within 10 s |
| 2.2 | Voice STT | Whisper.cpp + microphone | wake word `火种` triggers VAD; transcript matches utterance |
| 2.3 | Voice TTS | pyttsx3 + speakers | speaks the daily briefing in current language |
| 2.4 | Local vision | webcam + ONNX yolov8n | `vision identify <photo.jpg>` returns 1+ object class with confidence |
| 2.5 | RPi GPIO power monitor | RPi4/5 + ADC HAT | power.daily_consumption tracks within ±5% of reference draw |
| 2.6 | RPi I2C sensors | RPi + DHT22/BMP280/GPS | sensor_hub reports temp/humidity/pressure/lat-lng |

## 3. Multi-node spark network (run before any spark-net change)

| # | Item | Setup | Pass criteria |
|---:|------|-------|---------------|
| 3.1 | UDP beacon discovery | two `allspark` processes on the same LAN | each shows the other in `network` within 30 s |
| 3.2 | TCP knowledge exchange | initiator runs `network trade <peer> --offer foo --request bar` | proposal lands on peer; accept/reject persists |
| 3.3 | Unsupported transport boundary | inspect Network status with LAN unavailable and radio detection enabled | Bluetooth/Wi-Fi Direct are not presented as working data transports; availability detection remains Experimental/Unavailable |

## 4. Docker elastic deploy (SHA-33 partial)

| # | Item | Setup | Pass criteria |
|---:|------|-------|---------------|
| 4.1 | DOCKER mode start | 8GB+ machine with docker daemon | `docker status` shows core+web running; `/api/status` reachable |
| 4.2 | INTEGRATION mode start | 32GB+ with Kiwix+Ollama installed | hooks to existing Ollama; falls back to internal LLM if missing |
| 4.3 | Cross-mode reset | Docker mode → `reset 3` | containers stopped, volumes removed, mode degrades to PROCESS |

## 5. Long-running scheduler (run for ≥ 30 min)

| # | Item | How | Pass criteria |
|---:|------|-----|---------------|
| 5.1 | Resource decay | leave idle 30 min | water/food/power decay rates match `config.RESOURCE_DECAY_*` |
| 5.2 | Goal critical check | create overdue goal → wait next tick | warning appears in briefing; timeline records auto event |
| 5.3 | Daily briefing | wait 24 sim-hours | new briefing entry; old one archived; no duplicate writes |

---

## How to use

1. Copy this file into the release PR description, tick boxes as you go.
2. Anything that fails: open a Linear issue with label `claude` + `Bug`,
   reference this checklist row.
3. Items not exercised because hardware/setup is unavailable: explicitly
   write "n/a — no GPU available" rather than leaving the box unchecked.
4. Update this file when you add/remove a category.

For v1.0.3, row 1.8 is release-blocking. Row 1.8W is a compatibility promotion
gate rather than a tag blocker because Windows + NVDA is explicitly excluded
from Stable support; an unavailable environment must be recorded as `not_run`,
never converted into a pass from design review or automated DOM evidence.

> Items in §2–§5 originate from SHA-36 and depend on environments
> outside the macOS dev box. Add cells as fixtures arrive.
