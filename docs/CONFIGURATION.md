# AllSpark Configuration Guide

This guide summarizes the local runtime layout, optional features, and operational boundaries for AllSpark.

## Installation

The non-developer offline installation path is the self-contained Apple Silicon
macOS bundle described in [Offline Delivery](OFFLINE_DELIVERY.md). It does not
require Python, pip, Git, Xcode, a model, or a network connection on the target
Mac. The commands below are source/developer installation paths.

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

On POSIX systems, AllSpark enforces `0700` on managed data, backup, and snapshot
directories and `0600` on SQLite and preservation files. A database path whose
ancestor chain is writable by group or other users is rejected, except for
POSIX sticky shared directories such as `/tmp`. User-controlled directory
symlinks in the sensitive storage path are rejected; root-owned system aliases
are resolved and their target chain is checked. These controls do not encrypt
the data; see [the privacy boundary](PRIVACY.md) for the data
inventory, deletion semantics, encryption decision, and Windows validation
status.

## Models

Local model files can be large and sensitive to licensing constraints. Keep model weights outside the repository. `.gguf` files are ignored by default.

LLM, RAG, vision, and voice capabilities are optional and should degrade gracefully when dependencies or model files are unavailable.

### Experimental LLM selection metadata

The optional init flow can select one catalog default from a detected RAM tier.
This is an Experimental eligibility heuristic, not a minimum-device,
compatibility, performance, or out-of-memory guarantee. No real release GGUF
runtime has been certified. File and runtime sizes below are catalog estimates
that must be remeasured for the exact artifact and backend before use.

| Tier | Eligibility threshold (heuristic) | Catalog default | Estimated GGUF size | Estimated runtime RAM |
|------|--------------:|---------------|----------:|------------:|
| Phantom | ≥ 2 GB | `qwen3-1_7b-instruct-q4` | ~1 GB | ~1.2 GB |
| Minimum | ≥ 4 GB | `qwen3-4b-instruct-q4` | ~2.5 GB | ~3 GB |
| Recommended | ≥ 8 GB | `qwen3-8b-instruct-q4` | ~5 GB | ~6 GB |
| Comfortable | ≥ 16 GB | `qwen3-14b-instruct-q4` | ~9 GB | ~11 GB |
| Flagship | ≥ 32 GB | `qwen3-32b-instruct-q4` | ~20 GB | ~24 GB |

The implementation catalog (defaults + override candidates) lives in
`allspark/data/models.yaml`. These rows describe current configuration behavior
only and do not expand the v1.0.3 Stable support boundary.

### Overriding the default model

Three ways to swap the default, in priority order:

1. **Environment variable** — highest priority:

   ```bash
   ALLSPARK_LLM_MODEL=deepseek-r1-distill-qwen-14b allspark
   ```

2. **`~/.allspark/config.toml`** — persists across runs:

   ```toml
   [llm]
   model = "deepseek-r1-distill-qwen-14b"
   ```

3. **Drop a custom `.gguf` into `~/.allspark/models/`** — the init wizard auto-detects it.

### Override catalog (advanced)

Models that ship in `models.yaml` but are NOT defaults — opt in via the override mechanism above:

| Name | Total / Activated | Min RAM | Best for |
|------|------------------:|--------:|----------|
| `deepseek-v4-flash` | 284B / 13B MoE | ≥ 192 GB | Workstation users wanting frontier reasoning |
| `deepseek-v4-pro` | 1.6T / 49B MoE | ≥ 1 TB | Datacenter-class deployments |
| `deepseek-r1-distill-qwen-14b` | 14B dense | ≥ 16 GB | Reasoning-heavy survival decision-making |
| `qwen3-coder-30b-a3b-instruct-q4` | 30B / 3B MoE | ≥ 32 GB | Tool-call / function-call heavy use |

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

## Local crisis-support resources

Psychology and crisis support remain Experimental and non-clinical. The
deterministic safety prompt works offline and never contacts a service by
itself. Configure locally appropriate contacts in `~/.allspark/config.toml`:

```toml
[crisis_support]
region = "Your region"
emergency_service = "Local emergency number or radio procedure"
crisis_line = "Local crisis service"
trusted_contact = "Trusted person and offline contact method"
```

Every field is optional. Values are displayed exactly as local operator data;
AllSpark does not verify, dial, message, or transmit them. If no contact is
configured, the product says so and gives a location-neutral fallback instead
of assuming a country or hardcoding a regional hotline. See
[the crisis-support boundary](CRISIS_SUPPORT.md).

## Environment variables

The current project primarily uses code defaults, local files, and runtime state. Documented variables:

| Variable | Purpose | Default |
|----------|---------|---------|
| `ALLSPARK_LLM_MODEL` | Override the LLM picked by the init wizard. Value should match a name in `allspark/data/models.yaml` or a custom `.gguf` filename in `~/.allspark/models/`. | (unset — use tier default) |
| `IMPORT_BUDGET_MS` | Budget for `scripts/bench_import.py --check`. Overrun emits `::warning::` (warn-only by default). | `600` |
| `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24` | CI-only, suppresses Node.js 20 deprecation warning. | (set in `.github/workflows/ci.yml`) |

Do not assume an environment variable exists unless it is documented here.

## Sensitive files checklist

Before sharing logs, archives, or a repository snapshot, verify it does not include:

- `~/.allspark/` data
- SQLite databases
- diary or survivor profile data
- local model weights
- backups or snapshots
- `.env` files
- keys, certificates, or credentials
