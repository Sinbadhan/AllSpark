# 🔥 AllSpark — Offline AI Survival System

**v0.7.0** | [中文](README_CN.md)

> **In extreme conditions, preserve and rebuild human civilization.**

AllSpark (AllSpark: A Survival-centric Offline AI Resource Kit) is an offline-first AI survival assistance system. It runs on hardware ranging from Raspberry Pi to laptops, providing knowledge, decision support, goal tracking, and community governance when civilization's infrastructure collapses.

---

## Core Principles

- **Offline First** — Runs without network; all data and models stored locally
- **Progressive Intelligence** — From pure rule engine to local LLM, elastically upgraded by hardware capability
- **Knowledge is Life** — Built-in multi-tier survival knowledge base with inter-node knowledge exchange
- **Adaptive Survival** — Automatically adjusts operation mode and interaction personality based on resource status
- **Civilization Preservation** — Records experience, verifies knowledge, passes on skills, rebuilds the foundation of civilization

---

## Feature Overview

### 🧠 Intelligence Engine
| Feature | Description |
|---------|-------------|
| Rule Engine | Deterministic survival advice based on knowledge base, intent recognition + knowledge retrieval |
| Local LLM | llama-cpp-python inference, Qwen2.5 series (1.5B~72B), auto-selected by hardware |
| Survival Assessment | 5-dimensional resource assessment + phase determination + bottleneck identification |
| Personality System | Crisis/Stable/Companion/Multiplayer/Renaissance — 5 adaptive modes |
| Experience Accumulation | Experience recording → pattern recognition → knowledge entry loop |
| Daily Briefing | Auto-generated survival report: resources + warnings + goals + tasks + knowledge tip |
| Psychology Tracking | Loneliness/stress index + self-assessment questionnaire + intervention triggers |

### 🎯 Goal & Mission System
| Feature | Description |
|---------|-------------|
| Goal Engine | Auto-generate goals from resource state + 6 templates + manual goals |
| Milestone Tracking | Milestones auto-calculate progress; all done → goal completed |
| Goal-Task Linkage | Goals → tasks bi-directional sync; completing tasks advances milestones |
| Weather-Goal Linkage | Severe weather auto-pauses outdoor goals + creates shelter reinforcement |
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
| AllSpark Network | UDP beacon + TCP knowledge exchange, LAN/Bluetooth/WiFi Direct |
| Knowledge Trading | Propose/accept/reject/evaluate inter-node knowledge exchange protocol |
| Image Recognition | Multi-modal LLM analysis (plants/wounds/hazards/shelters/water/tools) |

### 👥 Multiplayer & Governance
| Feature | Description |
|---------|-------------|
| Permission System | Commander/Specialist/Executor/Observer — 4-tier roles + permission matrix |
| Dynamic Roles | Auto-recommend role promotion based on contribution and skills |
| Conflict Mediation | Create → AI mediation → resolution full workflow |
| Survival Value | 5-dimensional assessment (commander-only, advisory only) |
| Organization Assessment | Auto-evaluate structure rationality, suggest grouping/role additions |

### 🌍 Environment & Navigation
| Feature | Description |
|---------|-------------|
| GPS Manager | Sensor/manual positioning + position persistence + track recording + Haversine distance + bearing |
| Environment Assessment | 4-dimensional: climate/terrain/threats/opportunities + composite score |
| Weather Prediction | Barometric pressure → 12h forecast (clear/rain/storm) + cloud guide |
| Map System | Text-based map + POI management + category view |

### 📝 Journal & Timeline
| Feature | Description |
|---------|-------------|
| Spark Diary | Text/emotion recording + keyword tagging + date index + privacy protection |
| Survival Timeline | 7 event types + day-by-day view + auto-record goals/milestones/resource changes |
| Diary-Timeline Link | Diary entries auto-appear in survival timeline |

### 🎙️ Voice Interaction
| Feature | Description |
|---------|-------------|
| Speech-to-Text | Whisper multi-language model, microphone recording + file transcription |
| Text-to-Speech | pyttsx3 offline voice output |
| Voice Diary | Speak → transcribe → auto-save to diary system |
| Graceful Fallback | Friendly install hints when Whisper/pyttsx3 not available |

### 🐳 Docker Elastic Deployment
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
| Power Monitor | RPi GPIO ADC + simulated/manual fallback, power source registration + runtime estimation |
| Sensor Hub | I2C/GPIO/Serial multi-interface, 8 sensor types auto-detection |
| Data Preservation | Timed save + emergency save + snapshot/restore + signal handling + integrity check |
| Boot Optimization | Boot timing + systemd service template + watchdog script |
| Startup Integrity | DB file + table integrity + missing table detection on startup |

### 🖥 Interface
| Interface | Description |
|-----------|-------------|
| CLI | Rich-enhanced terminal, bilingual Chinese/English commands (30+ commands) |
| Web UI | FastAPI + responsive frontend, accessible from phone/tablet/desktop |
| Init Wizard | CLI/Web dual mode, language → hardware check → model → survivor profile |
| i18n | Full Chinese/English bilingual system with runtime language switching |

---

## Quick Start

### Installation

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
help                    — Full help
```

---

## Hardware Requirements

| Tier | RAM | Storage | Device | LLM Model |
|------|-----|---------|--------|-----------|
| Phantom | 2 GB | 16 GB | Raspberry Pi 4 | Qwen2.5-1.5B-Q4 |
| Minimum | 4 GB | 32 GB | Raspberry Pi 5 | Qwen2.5-3B-Q4 |
| Recommended | 8 GB | 64 GB | Mini PC | Qwen2.5-7B-Q4 |
| Comfortable | 16 GB | 128 GB | Laptop | Qwen2.5-14B-Q4 |
| Flagship | 32 GB+ | 256 GB+ | Workstation | Qwen2.5-72B-Q4 |

> Without LLM, the system still runs normally via the rule engine, only losing open-ended Q&A capability.

---

## Project Structure

```
AllSpark/
├── pyproject.toml                  # Project configuration
├── LICENSE                         # Apache 2.0
├── README.md                       # This file (English)
├── README_CN.md                    # Chinese README
├── PRD.md                          # Product Requirements Document
├── ARCHITECTURE.md                 # Architecture design document
│
├── tests/                          # Automated tests (331 tests)
│   ├── test_database.py            # Database CRUD + aggregation
│   ├── test_resource_manager.py    # Resource management
│   ├── test_governance.py          # Governance + permissions
│   ├── test_skf_manager.py         # SKF checksum + export/import
│   ├── test_i18n.py                # Internationalization
│   ├── test_data_preservation.py   # Data preservation + integrity
│   ├── test_goal_engine.py         # Goal engine + milestones
│   ├── test_reset_manager.py       # 3-level reset + cooldown
│   ├── test_v04_modules.py         # Briefing/timeline/diary/weather/psychology
│   ├── test_v05_modules.py         # GPS + environment
│   ├── test_v06_voice.py           # Voice interaction
│   ├── test_functional.py          # CLI functional tests
│   └── test_docker.py              # Docker elastic deployment
│
└── allspark/                       # Core code (63 modules)
    ├── __main__.py                 # Entry point
    ├── __init__.py                 # Version
    ├── cli.py                      # CLI interface (CommandDispatcher)
    ├── web_ui.py                   # Web UI (FastAPI)
    ├── bootstrap.py                # Application bootstrap & initialization
    ├── container.py                # Service container (dependency injection)
    │
    ├── models.py                   # Data models
    ├── database.py                 # SQLite database layer (FTS5)
    ├── config.py                   # Configuration constants
    ├── i18n.py                     # Internationalization (700+ keys)
    │
    ├── rule_engine.py              # Rule engine (core dispatch)
    ├── survival_engine.py          # Survival assessment
    ├── mission_planner.py          # Mission planning
    ├── knowledge_engine.py         # Knowledge engine
    ├── knowledge_loader.py         # Unified knowledge loading
    ├── resource_manager.py         # Resource management
    ├── personality.py              # Personality system
    ├── map_system.py               # Map system
    ├── experience_engine.py        # Experience accumulation
    ├── llm_engine.py               # Local LLM
    │
    ├── goal_engine.py              # Goal engine (v0.3)
    ├── reset_manager.py            # Reset manager (v0.3)
    ├── skf_manager.py              # SKF knowledge pack
    ├── knowledge_verifier.py       # Knowledge verification
    ├── spark_network.py            # AllSpark Network
    ├── vision_engine.py            # Image recognition
    │
    ├── governance.py               # Community governance
    ├── trade_engine.py             # Knowledge trading
    │
    ├── daily_briefing.py           # Daily briefing (v0.4)
    ├── timeline.py                 # Survival timeline (v0.4)
    ├── diary.py                    # Spark diary (v0.4)
    ├── weather.py                  # Weather prediction (v0.4)
    ├── psychology.py               # Psychology tracking (v0.4)
    │
    ├── gps_manager.py              # GPS manager (v0.5)
    ├── environment.py              # Environment assessor (v0.5)
    │
    ├── voice.py                    # Voice interaction (v0.6)
    │
    ├── docker_manager.py           # Docker container management (v0.7)
    ├── hardware.py                 # Hardware detection + DeployMode
    ├── module_loader.py            # Module registry
    ├── init_wizard.py              # Init wizard
    ├── tokenizer.py                # Chinese tokenizer
    │
    ├── commands/                   # Command pattern (v0.7)
    │   ├── base.py                 # BaseCommand abstract class
    │   ├── dispatcher.py           # CommandDispatcher
    │   ├── basic.py                # Status/resource/help commands
    │   ├── survival.py             # Survival/assessment commands
    │   ├── knowledge.py            # Knowledge/search commands
    │   ├── ai.py                   # LLM/experience commands
    │   ├── goals.py                # Goal/task/reset commands
    │   ├── governance.py           # Community/permission commands
    │   ├── comms.py                # Network/trade commands
    │   ├── hardware.py             # Power/sensor/preserve commands
    │   ├── docker.py               # Docker management commands
    │   └── help.py                 # Help command
    │
    ├── docker/                     # Docker configuration (v0.7)
    │   ├── Dockerfile.core         # Core service image
    │   ├── Dockerfile.llm          # LLM service image
    │   ├── Dockerfile.web          # Web UI service image
    │   └── docker-compose.yml      # Service orchestration
    │
    ├── power_monitor.py            # Power monitoring
    ├── sensor_hub.py               # Sensor hub
    ├── data_preservation.py        # Data preservation
    ├── boot_manager.py             # Boot management
    │
    ├── knowledge_data.py           # Tier 0 knowledge (Chinese)
    ├── knowledge_data_en.py        # Tier 0 knowledge (English)
    ├── knowledge_data_tier12.py    # Tier 1-2 knowledge
    └── knowledge_data_tier3.py     # Tier 3 knowledge
```

---

## Development Phases

| Phase | Content | Status |
|-------|---------|--------|
| 1 — MVP | Rule engine + Tier 0 knowledge + CLI + 5D resources + personality + map | ✅ |
| 2 — Intelligence | jieba tokenizer + local LLM + experience + Web UI + Tier 1-2 + i18n | ✅ |
| 3 — Connectivity | SKF pack + knowledge verification + AllSpark Network + image recognition | ✅ |
| 4 — Multiplayer | Permission system + dynamic roles + conflict mediation + knowledge trading + Tier 3 | ✅ |
| 5 — Hardware | Power monitor + sensors + data preservation + boot optimization | ✅ |
| 6 — Goals & Environment | Goal engine + 3-level reset + daily briefing + timeline + diary + weather + psychology + GPS + environment + voice | ✅ |
| 7 — Architecture & Docker | ServiceContainer DI + Command pattern + Bootstrap + i18n purification + Docker elastic deployment | ✅ |

---

## Testing

```bash
# Run all 331 tests
python3 -m pytest tests/ -v

# Run specific module
python3 -m pytest tests/test_goal_engine.py -v
```

---

## Contributing

Contributions are welcome! You can:

- Submit Issues to report bugs or suggest features
- Submit Pull Requests to improve code
- Expand knowledge base content (Tier 0-3 entries)
- Translate knowledge base to more languages

---

## License

Apache License 2.0

---

> *The AllSpark endures, civilization persists.*
