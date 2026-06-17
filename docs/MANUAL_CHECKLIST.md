# Manual Verification Checklist

> **Purpose:** Cover what the automated `pytest tests/` suite cannot —
> live LLM, voice/vision hardware, cross-node spark networking, Docker
> elastic deployment, and long-running schedulers. Run before tagging
> any minor or major release; record results in the release PR.
> **Tracks:** SHA-36

CI on GitHub runs `ruff` + `mypy` + `python scripts/bench_import.py
--check` on Python 3.10/3.11/3.12. The `tests/` tree is gitignored
(internal-only, see SHA-28); contributors should run it locally with
`pytest tests/ -q`. Everything else lives here.

---

## 1. Release-blocking checks (run for every tag)

| # | Item | How | Pass criteria |
|---:|------|-----|---------------|
| 1.1 | CLI cold start | `python -m allspark` from a fresh `~/.allspark/` | wizard runs to completion in expected language; status panel renders |
| 1.2 | Web UI cold start | `python -m allspark --web` then open `http://localhost:8000` | init wizard appears in browser language; no 500 in `/api/status` |
| 1.3 | i18n round-trip | start zh → switch to en in CLI and Web → switch back | no Chinese in en mode; no English in zh mode (modulo user-typed content) |
| 1.4 | Reset L1/L2/L3 | `reset 1` → confirm → `reset 2` → confirm → `reset 3` → confirm | each level honors 24h cooldown; rejected returns reason; L3 returns to wizard |
| 1.5 | SKF export/import round-trip | `skf export ~/Desktop/test.skf` → fresh DB → `skf import ~/Desktop/test.skf` | same knowledge count after import; SHA256 verified |
| 1.6 | Backup auto-snapshot | quit cleanly → check `~/.allspark/backups/` | latest snapshot has `_clean.db` and `_metadata.json` |

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
| 3.3 | Bluetooth fallback | LAN disabled, Bluetooth paired | discovery still completes; latency < 5 s round-trip |

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

> Items in §2–§5 originate from SHA-36 and depend on environments
> outside the macOS dev box. Add cells as fixtures arrive.
