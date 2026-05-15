# 🔥 AllSpark — Offline AI Survival System

**v0.2.0** | [中文](README.md)

> **In extreme conditions, preserve and rebuild human civilization.**

AllSpark (AllSpark: A Survival-centric Offline AI Resource Kit) is an offline-first AI survival assistance system. It runs on hardware ranging from Raspberry Pi to laptops, providing knowledge, decision support, and community governance when civilization's infrastructure collapses.

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

### 📚 Knowledge System
| Tier | Content | Entries |
|------|---------|---------|
| Tier 0 | Immediate survival (water/fire/food/shelter/medical) | 23 |
| Tier 1 | Short-term survival (agriculture/chemistry/mechanics/weather/energy) | 10 |
| Tier 2 | Mid-term self-sufficiency (composting/paper-making/hydropower/biogas/herbal) | 10 |
| Tier 3 | Long-term community (governance/forging/power generation/law/civilization archives) | 17 |

### 📡 Connectivity & Communication
| Feature | Description |
|---------|-------------|
| SKF Knowledge Pack | ZIP format standardized knowledge import/export |
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

### ⚡ Hardware Adaptation
| Feature | Description |
|---------|-------------|
| Power Monitor | RPi GPIO ADC + simulated/manual fallback, power source registration + runtime estimation |
| Sensor Hub | I2C/GPIO/Serial multi-interface, 8 sensor types auto-detection |
| Data Preservation | Timed save + emergency save + snapshot/restore + signal handling |
| Boot Optimization | Boot timing + systemd service template + watchdog script |

### 🖥 Interface
| Interface | Description |
|-----------|-------------|
| CLI | Rich-enhanced terminal, bilingual Chinese/English commands |
| Web UI | FastAPI + responsive frontend, accessible from phone/tablet/desktop |
| Init Wizard | CLI/Web dual mode, hardware check → language → model → survivor profile |

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
knowledge <keyword>     — Search knowledge base
experience log <event> <result>  — Record experience
map add <name> <type>   — Add map POI
llm load               — Load LLM model
skf export <path>      — Export knowledge pack
community add <name> [role] — Add community member
power status           — Power monitor status
preserve snapshot [tag] — Create data snapshot
help                   — Full help
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

### Feature Availability Matrix

| Feature | Phantom | Minimum | Recommended | Comfortable | Flagship |
|---------|---------|---------|-------------|-------------|----------|
| Rule Engine | ✅ | ✅ | ✅ | ✅ | ✅ |
| Local LLM | 1.5B | 3B | 7B | 14B | 72B |
| Knowledge (FTS+RAG) | FTS | FTS+light RAG | FTS+RAG | FTS+RAG | FTS+full RAG |
| Image Recognition | ❌ | ⚠️ | ✅ | ✅ | ✅ |
| Web UI | ❌ | ⚠️ | ✅ | ✅ | ✅ |
| Governance | ❌ | ❌ | ✅ | ✅ | ✅ |
| Knowledge Trading | ❌ | ❌ | ⚠️ | ✅ | ✅ |
| Power Monitor | ❌ | ⚠️ | ✅ | ✅ | ✅ |
| Sensor Hub | ❌ | ❌ | ⚠️ | ✅ | ✅ |
| Data Preservation | ❌ | ✅ | ✅ | ✅ | ✅ |
| Boot Optimization | ❌ | ❌ | ⚠️ | ✅ | ✅ |

---

## Project Structure

```
AllSpark/
├── pyproject.toml                  # Project configuration
├── README.md                       # Chinese README
├── README_EN.md                    # This file
│
└── allspark/                       # Core code
    ├── __main__.py                 # Entry point
    ├── __init__.py                 # Version
    ├── cli.py                      # CLI interface
    ├── web_ui.py                   # Web UI (FastAPI)
    │
    ├── models.py                   # Data models
    ├── database.py                 # SQLite database layer
    ├── config.py                   # Configuration constants
    ├── i18n.py                     # Internationalization
    │
    ├── rule_engine.py              # Rule engine
    ├── survival_engine.py          # Survival assessment
    ├── mission_planner.py          # Mission planning
    ├── knowledge_engine.py         # Knowledge engine
    ├── knowledge_loader.py         # Unified knowledge loading
    ├── resource_manager.py         # Resource management
    ├── personality.py              # Personality system
    ├── map_system.py               # Map system
    ├── experience_engine.py        # Experience accumulation
    ├── llm_engine.py              # Local LLM
    │
    ├── skf_manager.py             # SKF knowledge pack
    ├── knowledge_verifier.py      # Knowledge verification
    ├── spark_network.py           # AllSpark Network
    ├── vision_engine.py           # Image recognition
    │
    ├── governance.py              # Community governance
    ├── trade_engine.py            # Knowledge trading
    │
    ├── power_monitor.py           # Power monitoring
    ├── sensor_hub.py              # Sensor hub
    ├── data_preservation.py       # Data preservation
    ├── boot_manager.py            # Boot management
    │
    ├── hardware.py                # Hardware detection
    ├── module_loader.py           # Module registry
    ├── init_wizard.py             # Init wizard
    ├── tokenizer.py               # Chinese tokenizer
    │
    ├── knowledge_data.py          # Tier 0 knowledge (Chinese)
    ├── knowledge_data_en.py       # Tier 0 knowledge (English)
    ├── knowledge_data_tier12.py   # Tier 1-2 knowledge
    └── knowledge_data_tier3.py    # Tier 3 knowledge
```

---

## API Endpoints

Web UI provides 70+ RESTful API endpoints:

| Module | Endpoints | Description |
|--------|-----------|-------------|
| Core | `/api/status` `/api/resources` `/api/tasks` `/api/chat` | Status/resources/tasks/chat |
| Knowledge | `/api/knowledge/search` `/api/knowledge/category` `/api/knowledge/detail` | Search/category/detail |
| LLM | `/api/llm/status` `/api/llm/load` `/api/llm/chat` | Model management/chat |
| Experience | `/api/experience/log` `/api/experience/patterns` | Record/patterns |
| SKF | `/api/skf/info` `/api/skf/export` `/api/skf/import` | Knowledge pack management |
| Verification | `/api/verify/stats` `/api/verify/entry` `/api/verify/batch` | Knowledge verification |
| Network | `/api/network/status` `/api/network/start` `/api/network/exchange` | AllSpark Network |
| Vision | `/api/vision/status` `/api/vision/analyze` | Image analysis |
| Governance | `/api/governance/members` `/api/governance/assess` `/api/governance/conflicts` | Community governance |
| Trade | `/api/trade/status` `/api/trade/propose` `/api/trade/evaluate` | Knowledge trading |
| Power | `/api/power/status` `/api/power/monitor/start` `/api/power/runtime` | Power monitoring |
| Sensor | `/api/sensor/status` `/api/sensor/snapshot` `/api/sensor/detect` | Environmental sensing |
| Preservation | `/api/preserve/status` `/api/preserve/snapshot` `/api/preserve/emergency` | Data protection |

---

## Development Phases

| Phase | Content | Status |
|-------|---------|--------|
| 1 — MVP | Rule engine + Tier 0 knowledge + CLI + 5D resources + personality + map | ✅ |
| 2 — Intelligence | jieba tokenizer + local LLM + experience + Web UI + Tier 1-2 | ✅ |
| 3 — Connectivity | SKF pack + knowledge verification + AllSpark Network + image recognition | ✅ |
| 4 — Multiplayer | Permission system + dynamic roles + conflict mediation + knowledge trading + Tier 3 | ✅ |
| 5 — Hardware | Power monitor + sensors + data preservation + boot optimization | ✅ |

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
