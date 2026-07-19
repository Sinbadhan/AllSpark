# 🔥 AllSpark — Offline AI Survival System

**v1.0.3** | Release Candidate | [中文](README_CN.md)

> **In extreme conditions, preserve and rebuild human civilization.**

AllSpark (AllSpark: A Survival-centric Offline AI Resource Kit) is an offline-first AI survival assistance system. The codebase includes desktop and Raspberry Pi adapters, but the v1.0.3 candidate targets only the desktop PROCESS-mode core described below. It has not been published as Stable.

---

## Core Principles

- **Offline First** — Runs without network; all data and models stored locally
- **Deterministic Core** — The supported loop works without a model; local LLM integration remains optional and Experimental
- **Knowledge is Life** — Built-in multi-tier survival knowledge base with inter-node knowledge exchange
- **Evidence Before Inference** — Unknown facts stay unknown; phase, urgency, and plans come from explicit observations and auditable rules
- **Civilization Preservation** — Records experience, verifies knowledge, passes on skills, rebuilds the foundation of civilization

---

## v1.0.3 Release Support Boundary

This table defines the intended public support scope. A release candidate is not
Stable until every gate in [the release checklist](docs/RELEASE_CHECKLIST.md)
passes; code presence alone is not validation.

| Status | Scope |
|--------|-------|
| Supported | Python 3.10-3.12 desktop PROCESS mode; CLI and Web UI; local SQLite; the **Assess -> Decide -> Act -> Reassess** loop; evidence-aware knowledge search/import/export; confirmed 24h plans; tasks and outcome reassessment; local snapshot/restore; Chinese/English; core Web flows with macOS VoiceOver |
| Testing | Windows screen-reader compatibility with NVDA. Design and automated checks are complete; a real Windows + NVDA run is still required. |
| Experimental | Experience/self-learning promotion; psychology and non-clinical crisis support (independent qualified expert review pending); personality adaptation; Governance/RBAC (disabled until member identity and server-side authorization are verified); knowledge trading; Docker/INTEGRATION; real GGUF/LLM and GPU acceleration; microphone/STT/TTS; camera/vision; Raspberry Pi GPIO/I2C/Serial, sensors, power and hardware GPS; cross-host Spark Network; weather/environment/map automation; removable-media disaster recovery |
| Future / not supported in v1.0.3 | Bluetooth, Wi-Fi Direct and LoRa transports; signed knowledge packs; complete multiplayer identity and governance. The current Spark Network transport is TCP over LAN; radio availability detection is not a transport implementation. |

Single-host, independent-process Spark Network exchange is covered by automated
integration tests. It does not certify cross-host radios or field deployment.
See [real-world validation](docs/REAL_WORLD_VALIDATION.md) for current evidence.
Windows screen-reader compatibility remains a testing-stage capability until a
real Windows + NVDA run is attached; it is not part of the v1.0.3 Stable
accessibility claim.

Bundled or imported knowledge whose content evidence and risk classification
have not both passed local review remains searchable as an inventory item, but
its summary, steps, prerequisites, warnings, applicability, and
contraindications are withheld from API, CLI, and Web action surfaces. The
bundled catalog is currently pending external review; metadata visibility is
not permission to act on unreviewed content.

---

## Feature Overview

This is a capability inventory, not a Stable commitment. Status labels here are
subordinate to the release support boundary above; unlabeled supporting tools
do not expand the primary v1.0.3 product promise.

### 🧠 Intelligence Engine
| Feature | Description |
|---------|-------------|
| Rule Engine | Deterministic survival advice based on knowledge base, intent recognition + knowledge retrieval |
| Local LLM (Experimental) | llama-cpp-python inference path and Qwen3 sizing recommendations; a release GGUF runtime has not been certified |
| Survival Assessment | Explicit Known/Unknown observations + normalized resources + auditable phase and bottleneck rules |
| Personality System (Experimental) | Crisis/Stable/Companion/Multiplayer/Renaissance adaptation prototype |
| Experience Accumulation (Experimental) | Experience recording → pattern recognition → knowledge entry promotion prototype |
| Daily Briefing | Auto-generated survival report: resources + warnings + goals + tasks + knowledge tip |
| Psychology Tracking (Experimental) | Non-clinical loneliness/stress prompts and self-assessment; explicit self-harm language enters private, deterministic safety confirmation before rules/LLM. No diagnosis, automatic notification, or silent timeline recording; qualified external review is pending. |

### 🎯 Goal & Mission System
| Feature | Description |
|---------|-------------|
| Goal Engine | Auto-generate goals from resource state + 6 templates + manual goals |
| Milestone Tracking | Milestones auto-calculate progress; all done → goal completed |
| Goal-Task Linkage | Goals → tasks bi-directional sync; completing tasks advances milestones |
| Weather-Goal Linkage (Experimental) | Severe weather auto-pauses outdoor goals + creates shelter reinforcement |
| 3-Level Reset | L1 (assessment) / L2 (archive) / L3 (factory) + safety constraints + cooldown |

### 📚 Knowledge System
| Tier | Content | Entries |
|------|---------|---------|
| Tier 0 | Immediate survival (water/fire/food/shelter/medical) | 23 |
| Tier 1 | Short-term survival (agriculture/chemistry/mechanics/weather/energy) | 10 |
| Tier 2 | Mid-term self-sufficiency (composting/paper-making/hydropower/biogas/herbal) | 10 |
| Tier 3 | Long-term community (governance/forging/power generation/law/civilization archives) | 17 |
| SKF Pack | ZIP format standardized knowledge import/export with SHA256 checksum |

### 📡 Connectivity & Communication
| Feature | Description |
|---------|-------------|
| Knowledge Verification | 5-step verification: format → source → consistency → cross-reference → rating |
| AllSpark Network (Experimental) | UDP discovery + LAN TCP knowledge exchange; single-host multi-process verified, cross-host not certified |
| Knowledge Trading (Experimental) | Propose/accept/reject/evaluate inter-node knowledge exchange protocol |
| Image Recognition (Experimental) | Multi-modal analysis path; camera and target model runtime are not certified |

### 👥 Multiplayer & Governance (Experimental, Disabled)
| Feature | Description |
|---------|-------------|
| Permission System (Experimental) | A role matrix exists in prototype code, but no request or CLI subject is bound to a community member; it is not an enforced RBAC boundary. |
| Governance operations (Unavailable) | Web and CLI member, role and conflict operations fail closed in v1. |
| Person-value ranking (Removed) | AllSpark does not score or rank people by health, psychological state, contribution, or other personal attributes. Legacy API/CLI calls return a uniform unsupported response. |

### 🌍 Environment & Navigation
| Feature | Description |
|---------|-------------|
| GPS Manager | Manual positioning is supported; physical GPS/sensor input remains Experimental |
| Environment Assessment (Experimental) | 4-dimensional: climate/terrain/threats/opportunities + composite score |
| Weather Prediction (Experimental) | Barometric pressure → 12h forecast (clear/rain/storm) + cloud guide |
| Map System (Experimental) | Text-based map + POI management + category view |

### 📝 Journal & Timeline
| Feature | Description |
|---------|-------------|
| Spark Diary | Text/emotion recording + keyword tagging + date index; local plaintext privacy boundary is documented |
| Survival Timeline | 7 event types + day-by-day view + auto-record goals/milestones/resource changes |
| Diary-Timeline Link | Diary entries auto-appear in survival timeline |

### 🎙️ Voice Interaction (Experimental)
| Feature | Description |
|---------|-------------|
| Speech-to-Text | Whisper multi-language model, microphone recording + file transcription |
| Text-to-Speech | pyttsx3 offline voice output |
| Voice Diary | Speak → transcribe → auto-save to diary system |
| Graceful Fallback | Friendly install hints when Whisper/pyttsx3 not available |

### 🐳 Docker Elastic Deployment (Experimental)
| Feature | Description |
|---------|-------------|
| Deploy Mode | PROCESS / DOCKER / INTEGRATION — auto-selected by hardware tier |
| Docker Manager | Container lifecycle management (start/stop/migrate/reset) |
| Docker Compose | Core/LLM/RAG/Web/Kiwix service orchestration |
| Elastic Fallback | Auto-downgrade to process mode when Docker unavailable |
| Reset Regression | L3 factory reset clears all containers, returns to process mode |

### ⚡ Hardware Adaptation
| Feature | Description |
|---------|-------------|
| Power Monitor (Experimental hardware) | Simulated/manual fallback is available; RPi GPIO ADC is not field-certified |
| Sensor Hub (Experimental) | I2C/GPIO/Serial adapters exist but target sensors are not field-certified |
| Data Preservation | Local atomic snapshot/restore + checksum/integrity checks + POSIX owner-only permissions; data is not application-encrypted and removable-media recovery is Experimental |
| Boot Optimization (Experimental) | Boot timing plus systemd/watchdog templates; target Linux boot deployment is not certified |
| Startup Integrity | DB file + table integrity + missing table detection on startup |

### 🖥 Interface
| Interface | Description |
|-----------|-------------|
| CLI | Rich-enhanced terminal, bilingual Chinese/English commands (30+ commands) |
| Web UI | FastAPI + responsive frontend, accessible from phone/tablet/desktop |
| Init Wizard | CLI/Web flow: language -> immediate-danger availability -> minimum assessment -> confirmed 24h plan; Web interruption recovery stays explicitly unpublished until atomic publish; hardware and model setup remain optional |
| i18n | Full Chinese/English bilingual system with runtime language switching |

---

## Quick Start

### Installation

AllSpark is released as an open-source project. Source archives and wheels are
the canonical release artifacts; publish them with checksums, dependency and
license notices, and the source commit. The optional target-specific portable
bundle documented in [Offline Delivery](docs/OFFLINE_DELIVERY.md) includes
Python, dependencies, core knowledge, integrity verification, and
install/rollback launchers. The supported loop requires no model.

The current portable-bundle target is macOS Apple Silicon. Developer ID signing
and notarization are required only when an official macOS App or DMG is offered
as a Gatekeeper-trusted convenience download; they do not block source, wheel,
or checksum-verified portable archive releases.

Install from source for development and advanced operation:

```bash
# Clone repository
git clone https://github.com/Sinbadhan/AllSpark.git && cd AllSpark

# Install dependencies
pip install -e .

# (Optional) Install local LLM support
pip install llama-cpp-python

# (Optional) RPi hardware support
pip install RPi.GPIO smbus2 pyserial

# (Optional) Voice interaction
pip install openai-whisper sounddevice pyttsx3
```

### Launch

```bash
# CLI mode (first launch auto-runs init wizard)
python3 -m allspark

# Web UI mode
python3 -m allspark --web
# or
python3 -m allspark -w
```

### Common Commands

```
status                  — View survival status and resources
resource                — View 5-dimensional resource details
goals                   — View and manage survival goals
briefing                — Generate daily survival briefing
diary add               — Write a diary entry
weather                 — Weather prediction
gps set <lat> <lon>     — Set GPS position
psychology              — View psychological state
environment             — Environment assessment
voice load              — Load Whisper speech model
docker status           — Docker deployment status
help                    — Full help
```

---

## Evidence-Based Deployment Planning

v1.0.3 does not publish a universal minimum RAM tier, recommended device, model,
tokens-per-second figure, power draw, or battery-life promise. Those outcomes
depend on the exact OS, CPU/GPU, storage, display, peripherals, content pack, and
model. The supported rule-based loop does not require an LLM.

Use [real-world validation](docs/REAL_WORLD_VALIDATION.md) for the current test
matrix. Docker/INTEGRATION, Raspberry Pi, real GGUF execution, sensors, and
removable-media recovery remain Experimental until reproducible evidence for a
named configuration is attached there. Offline delivery artifacts will carry
their own measured size, checksum, target platform, and rollback instructions.

---

## Project Structure

```
AllSpark/
├── pyproject.toml                  # Project configuration
├── LICENSE                         # Apache 2.0
├── README.md                       # This file (English)
├── README_CN.md                    # Chinese README
│
├── allspark/                       # Source code
│   ├── __main__.py                 # Entry point (CLI/Web mode switch)
│   ├── __init__.py                 # Version
│   ├── bootstrap.py                # Application bootstrap & initialization
│   ├── container.py                # ServiceContainer dependency injection
│   ├── base_service.py             # Shared service lifecycle base class
│   ├── docker_manager.py           # Docker container lifecycle management
│   ├── py.typed                    # PEP 561 typing marker
│   │
│   ├── adapters/                   # Presentation layer
│   │   ├── cli.py                  # Rich terminal REPL
│   │   ├── web_ui.py               # FastAPI app + init routes
│   │   ├── init_wizard.py          # CLI initialization wizard
│   │   └── routes/                 # Web API route modules
│   │
│   ├── commands/                   # Command pattern layer
│   │   ├── base.py                 # BaseCommand abstract class
│   │   ├── dispatcher.py           # Auto-discovery CommandDispatcher
│   │   ├── basic.py                # Status/resource/help commands
│   │   ├── survival.py             # Survival/assessment commands
│   │   ├── knowledge.py            # Knowledge/search commands
│   │   ├── ai.py                   # LLM/experience commands
│   │   ├── goals.py                # Goal/task/reset commands
│   │   ├── governance.py           # Community/permission commands
│   │   ├── comms.py                # Network/trade commands
│   │   ├── hardware.py             # Power/sensor/preservation commands
│   │   ├── docker.py               # Docker management commands
│   │   └── help.py                 # Help command
│   │
│   ├── core/                       # Core data/config layer
│   │   ├── config.py               # Configuration constants
│   │   ├── database.py             # SQLite database layer (FTS5)
│   │   ├── i18n.py                 # Internationalization loader
│   │   ├── models.py               # Data models
│   │   └── tokenizer.py            # Chinese tokenizer
│   │
│   ├── services/                   # Business service layer (~25 services)
│   │   ├── rule_engine.py          # Core decision engine
│   │   ├── resource_manager.py     # Resource management
│   │   ├── survival_engine.py      # Survival assessment
│   │   ├── mission_planner.py      # Mission planning
│   │   ├── knowledge_engine.py     # Knowledge retrieval
│   │   ├── knowledge_loader.py     # YAML knowledge loader
│   │   ├── goal_engine.py          # Goals + milestones
│   │   ├── priority_calculator.py  # Multi-dimensional priority scoring
│   │   ├── warning_protocol.py     # Resource warning closed loop
│   │   ├── vector_engine.py        # Hybrid FTS/vector retrieval
│   │   ├── external_kb.py          # Kiwix/Kolibri/ProtoMaps integration
│   │   ├── voice.py                # Voice session routing
│   │   └── ...                     # Governance, diary, weather, GPS, etc.
│   │
│   ├── infrastructure/             # Hardware/platform layer
│   │   ├── hardware.py             # Hardware detection + FeatureFlags
│   │   ├── module_loader.py        # Module registry
│   │   ├── data_preservation.py    # Snapshot/restore/integrity
│   │   └── boot_manager.py         # systemd/watchdog boot support
│   │
│   ├── data/                       # YAML survival knowledge data
│   │   └── knowledge/              # Tier 0-3 knowledge entries
│   ├── locales/                    # zh/en i18n YAML files
│   ├── templates/                  # Web UI HTML templates
│   └── docker/                     # Dockerfiles + docker-compose.yml
│
└── tests/                          # automated tests (tracked; count per `pytest tests -q`; runs on CI)
```

---

## Development Phases

| Phase | Content | Status |
|-------|---------|--------|
| 1 — MVP | Rule engine + Tier 0 knowledge + CLI + 5D resources + personality + map | ✅ |
| 2 — Intelligence | jieba tokenizer + local LLM + experience + Web UI + Tier 1-2 + i18n | Core complete; LLM Experimental |
| 3 — Connectivity | SKF pack + knowledge verification + AllSpark Network + image recognition | SKF complete; network/vision Experimental |
| 4 — Multiplayer | Experimental governance prototypes + knowledge trading + Tier 3 knowledge | Experimental |
| 5 — Hardware | Power monitor + sensors + data preservation + boot optimization | Local preservation complete; hardware Experimental |
| 6 — Goals & Environment | Goal engine + 3-level reset + daily briefing + timeline + diary + weather + psychology + GPS + environment + voice | Core complete; physical I/O Experimental |
| 7 — Architecture & Docker | ServiceContainer DI + Command pattern + Bootstrap + i18n purification + Docker elastic deployment | Architecture complete; Docker Experimental |

---

## Quality Status

| Check | Status |
|-------|--------|
| Automated tests | ✅ see CI / pytest output |
| Ruff lint | ✅ 0 errors |
| mypy | ✅ CI-enforced with `check_untyped_defs`; no disabled error-code categories |
| Packaging types | ✅ `py.typed` included |
| Public repo hygiene | ✅ Tests tracked for reproducible CI; runtime data, local models, secrets, and build output ignored |

---

## Testing

```bash
# Run the full test suite
python3 -m pytest tests/ -v --tb=short

# Run specific module
python3 -m pytest tests/test_goal_engine.py -v
```

---

## Contributing

Contributions are welcome. Start with these project documents:

- [Contributing Guide](CONTRIBUTING.md) — development setup, checks, PR expectations, coding conventions
- [Security Policy](SECURITY.md) — private vulnerability reporting and sensitive data boundaries
- [Code of Conduct](CODE_OF_CONDUCT.md) — community behavior expectations
- [Changelog](CHANGELOG.md) — release history
- [Configuration Guide](docs/CONFIGURATION.md) — local data, optional features, Docker modes, SKF/network boundaries
- [Release Checklist](docs/RELEASE_CHECKLIST.md) — version, QA, packaging, and release steps

---

## License

Apache License 2.0

---

> *The AllSpark endures, civilization persists.*
