# AllSpark Configuration Guide

This guide summarizes the local runtime layout, optional features, and operational boundaries for AllSpark.

## Installation

```bash
pip install -e .
```

For development tools:

```bash
pip install -e ".[dev]"
```

Optional feature groups:

```bash
pip install -e ".[rag]"     # vector/RAG dependencies
pip install -e ".[vision]"  # local vision dependencies
pip install -e ".[voice]"   # voice dependencies
```

## Running AllSpark

CLI mode:

```bash
python3 -m allspark
```

Web UI mode:

```bash
python3 -m allspark --web
```

If the package script is installed and on PATH:

```bash
allspark
```

## Local data

AllSpark is offline-first and stores runtime data locally. Treat runtime data as sensitive because it may contain survivor profiles, locations, diaries, resources, local knowledge, and operational history.

Common local data locations and file types:

- `~/.allspark/`
- `~/.spark/` legacy migration source
- SQLite databases and journals
- backups and snapshots
- logs

Do not commit local runtime data to Git.

## Models

Local model files can be large and sensitive to licensing constraints. Keep model weights outside the repository. `.gguf` files are ignored by default.

LLM, RAG, vision, and voice capabilities are optional and should degrade gracefully when dependencies or model files are unavailable.

## Hardware profiles

AllSpark is designed to scale from low-resource devices to more capable offline systems:

| Tier | Typical hardware | Expected mode |
|------|------------------|---------------|
| Minimal | 2-4GB RAM | Core process mode, degraded optional modules |
| Recommended | 8-16GB RAM | More optional modules, possible Docker mode |
| Comfortable | 32GB+ RAM | Docker/NOMAD integration candidates |

Real RPi GPIO, sensor, GPS, microphone, and power-monitoring validation remains hardware-dependent and should be tested on target devices before relying on it.

## Docker deployment modes

AllSpark uses an elastic deployment model:

- `PROCESS`: run services directly in the Python process, suitable for low-memory systems.
- `DOCKER`: run selected services in containers when Docker and hardware capacity are available.
- `INTEGRATION`: reserved for higher-capacity integration with broader offline knowledge stacks.

The system should fall back toward simpler modes when Docker is unavailable.

## Network and SKF packages

SKF packages and network exchange payloads should be treated as untrusted inputs unless their source is known. Importing knowledge can affect survival decisions, so validation and review matter.

Current network features are best treated as LAN/local-trust prototypes. Disaster-channel transports such as Bluetooth, LoRa, or SD-card exchange require additional validation and security design.

## Environment variables

The current project primarily uses code defaults, local files, and runtime state. Do not assume an environment variable exists unless it is documented in code. Future environment variables should be added here with defaults, safety notes, and examples.

## Sensitive files checklist

Before sharing logs, archives, or a repository snapshot, verify it does not include:

- `~/.allspark/` data
- SQLite databases
- diary or survivor profile data
- local model weights
- backups or snapshots
- `.env` files
- keys, certificates, or credentials
