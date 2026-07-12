# Changelog

All notable changes to AllSpark are documented here.

This project follows the spirit of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Version numbers are tracked in `pyproject.toml` and `allspark/__init__.py`.

## [Unreleased]

### Audit remediation (SHA-158, 2026-07-11)

Full publish-readiness audit (SHA-158) remediation - 15 issues closed across
security, quality, UX, and packaging. Audit baseline Off track -> only
real-hardware verification (SHA-33) remains.

**Security (P0):**
- SHA-142: Web auth boundary - token moved out of HTML to httpOnly+SameSite
  cookie; `/login` + `/api/auth/login`; one-time bootstrap (init/complete 410
  after init); middleware always on (loopback local trust, non-loopback gated).
- SHA-147: SKF persistent XSS - input sanitization (`_sanitize_kf_field`) +
  output escaping (escHtml) on knowledge metadata fields.
- SHA-148: Knowledge `expert_verified` signoff schema (reviewer/qualification/
  date/citation/content_hash/signoff_version) + content-hash invalidation;
  142 entries downgraded to field_tested; loader + verifier gating.
- SHA-28: Full test suite tracked in VCS + CI pytest (was gitignored, 55 tests
  -> 730 tracked); CI coverage gate + collection-count gate.

**Quality (P1):**
- SHA-150: NL survival Q&A - FTS5 bm25 + title-substring re-rank; 1 main
  answer + 2 related links (not full-text concat); 50+ golden set.
- SHA-149: System health score factors in core capabilities (LLM/modules);
  weather structured rendering (no raw JSON/null).
- SHA-151: Coverage gate (`--cov-fail-under=60`) + collection-count gate;
  init_wizard critical-path tests (10% -> 20%).
- SHA-152: Web a11y - button semantics (lang cards/chips), modal dialog
  role/Esc/focus, icon aria-labels.

**UX (P2):**
- SHA-153: Repository browser - search/category/tier/verification/language
  filter + pagination + row detail modal + full ID tooltip.
- SHA-154: Config page - real read-only view (about+health APIs); removed
  hardcoded configTemplates/SAVED editor chrome.
- SHA-155: CLI cold-start - `render(g.title)` (no marker leak); jieba/
  VectorEngine log noise suppressed.
- SHA-143: Doc/version/CI consistency (single source = CI output) +
  `test_doc_consistency` guard.

**Packaging/hygiene (P3):**
- SHA-144: bench_import - dual metric (sum-of-means micro-bench + wall-clock
  SLO) with independent budgets; `--hard-fail` on either.
- SHA-156: Web dead-entry cleanup (exec-btn -> /executions; removed dead docs
  link; dedup settings icon).
- SHA-157: Package metadata - PEP 639 license; removed deprecated classifier;
  removed unused prompt-toolkit; MANIFEST `*.j2` fix; Python 3.10 `tomli`
  conditional dep; CI clean-wheel smoke matrix (3.10/3.11/3.12).
- SHA-145: Starlette/httpx2 deprecation warning cleared (httpx2 declared).

Remaining: SHA-33 real-hardware verification (RPi/sensors/LLM/Docker/multi-node)
- needs physical hardware, cannot be mocked/skipped.

### Security
- **H1**: Fixed `KnowledgeSigner._derive_key` bug — `getattr(self.db, "_db_path")`
  referenced a non-existent attribute (actual: `db_path`), so every installation
  derived the same HMAC key from the constant `"allspark-default"`. Key is now
  per-node. Cross-node verification still requires a shared secret (v2.0 PKI per ADR 003).
- **H2**: Spark Network TCP exchange server hardening — added
  `SPARKNET_MAX_INCOMING_BYTES` (50 MB) cap to prevent memory-exhaustion DoS;
  wired soft signature verification on the receive path (entries carrying a
  signature are verified against a configurable `network_shared_secret`,
  mismatches rejected; unsigned entries still accepted as unverified for
  backward compatibility); added connection/transfer logging; replaced silent
  `except Exception: pass` with logged handlers.
- **H3**: Web API bearer-token auth — when the Web UI binds a non-loopback host
  (`--host 0.0.0.0` or LAN IP), a bearer token is now required for all `/api/*`
  routes (auto-generated unless `--web-token` is given). `/api/init/*` stays
  open so the init wizard can bootstrap. The token is injected into HTML
  templates and the browser fetch wrapper adds the `Authorization` header
  automatically.

### Changed
- **L1/L2**: DI fixes — `commands/ai.py` VerifyCommand now uses
  `container.get("knowledge_verifier")` instead of constructing directly;
  `VisionEngine` is registered as a factory in bootstrap so `commands/comms.py`
  no longer constructs/registers it manually; removed duplicate
  `registry.register("self_learning", True)` in bootstrap (dead code).
- **L3**: `vision_engine._check_multimodal` now reads `LLMEngine.get_status()`
  instead of the private `_model_path` attribute.
- **L8**: Added major-version upper bounds to runtime and dev dependencies
  (`pyyaml<7`, `rich<16`, `fastapi<1`, `uvicorn<1`, `jinja2<4`, etc.).
- **M4**: ~15 silent `except Exception:` handlers in `database.py`,
  `data_preservation.py`, `sensor_hub.py`, `timeline.py`, `boot_manager.py`,
  `trade_engine.py` now log at warning/debug with context. Control flow unchanged.

### i18n
- Cleared ~76 hardcoded user-visible strings across `adapters/routes/`,
  `services/` (llm_engine, voice, skf_manager, experience_engine), and
  `commands/` (governance, docker, survival). 67 new locale keys added to
  `zh.yaml`/`en.yaml`. Web API error responses now go through `t()`.

### Documentation
- Updated `CLAUDE.md` from stale v0.7.0 to v1.0.3 (version, test count,
  directory structure, mypy `check_untyped_defs` status, command class count).
- `CONTRIBUTING.md`: corrected stale mypy allowlist note; documented that CI
  does not run pytest and `tests/` is private.

## [1.0.3] - 2026-06-24

Stability convergence release. Closes the 2026-06-23 audit backlog — 9 Linear
issues (SHA-36, 37, 40, 55, 56, 57, 58, 59, 60) covering two P1 contract bugs
and the P2/P3 quality debt. Automated suite grows from 589 → 612 passed with
6 hardware-gated live tests; mypy now runs clean with **zero** disabled error
codes; the regression harness separates allowed degradation from real failures.

### Fixed
- **SHA-55** (P1): Web UI/API contract drift — `system.html` read the legacy
  `m.loaded`/`m.can_load` fields the `/api/modules` endpoint never returned,
  so every module rendered as "disabled"; `repository.html` read `e.category`
  which the category endpoint omits, producing `undefined` in the knowledge
  table. Frontend now reads the actual `status`/`hw_supported` fields and
  re-tags the category client-side. Added contract pytest guards.
- **SHA-56** (P1): Init wizard structured questionnaire was unreachable — the
  CLI loader pointed at `adapters/data/questionnaire.yaml` (non-existent)
  instead of `allspark/data/questionnaire.yaml`, silently degrading to
  free-text. Web init wizard only collected `survivor-name`. Fixed the path,
  added a `/api/init/questionnaire` endpoint, extended the Web Step 4 with the
  full PRD §4.2.2 questionnaire (location/shelter/health/urgency/threats/
  skills), and `/api/init/complete` now accepts a JSON body and persists
  `questionnaire_version=2` plus the key fields.
- **SHA-60**: Two real i18n bugs surfaced during harness triage — the topbar
  `page_title` was hardcoded English ("Dashboard", "System Monitor", …) and
  leaked into zh mode; goal `rationale` was persisted as a translated string
  (baked in at startup language) instead of a `mark()` key, surviving a later
  `lang` switch. Both now route through `t()`/`render()`.

### Added
- **SHA-37**: English knowledge YAML for tier1/2/3 (10/10/17 entries),
  closing the bilingual gap — English users previously got only Tier 0.
  Loader registers the `_en.yaml` files; bilingual-parity + English-title
  pytest guards prevent future drift.
- **SHA-36**: `tests/test_sha36_regression.py` (14 cases) — Spark Network
  two-node loopback handshake/exchange/transfer, Docker graceful degradation
  without a daemon, and adaptive TaskScheduler long-time scenarios driven by
  `_last_run` manipulation instead of sleeping. `tests/test_live_smoke.py`
  plus five pytest markers (`requires_llm`/`requires_voice`/`requires_vision`/
  `requires_network`/`requires_docker`) gate hardware-dependent checks so they
  no longer fold into the automated "done" count.
- **SHA-59**: In-app toast + modal layer (`toast()`, `confirmDialog()`,
  `promptDialog()`) replacing native `alert`/`confirm`/`prompt` across all
  templates, with a regression test asserting no native dialogs remain.
- **SHA-58**: CSS token aliases (`--surface-container*`) and a minimal
  Tailwind-style utility subset so previously-dropped class declarations
  resolve; Material Symbols offline fallback (`.icons-offline` hides ligature
  text when the font is unavailable).

### Changed
- **SHA-40**: mypy `disable_error_code` block removed entirely — all four
  previously-suppressed codes (assignment/arg-type/operator/attr-defined, 68
  errors across 18 files) paid down. Regular `mypy allspark/` is green with no
  overrides.
- **SHA-57**: PROGRESS/TECH-DECISIONS/README/ARCHITECTURE synced to v1.0.2 →
  v1.0.3 and Qwen2.5 → Qwen3; stale test counts replaced with "per pytest
  output"; `AUDIT_2026-06-17.md` marked historical.
- **SHA-60**: Regression harness now tags expected 503s (network/vision with
  no backing hardware) as `degraded_allowlisted` with an explicit reason, and
  the combined `INDEX.md` states the triage verdict so a release gate can
  distinguish blocking failures from allowed degradation at a glance. CLI/HTML
  false-positive heuristics tightened (startup-banner segmentation, icon
  ligature span stripping, GPS acronym allowlist).

## [1.0.2] - 2026-06-17

Maintenance release. Externalizes the LLM model registry, upgrades
default models from Qwen2.5 to Qwen3 across all hardware tiers, and
adds an override mechanism so workstation users can opt into frontier
models like DeepSeek-V4-Flash without code changes.

### Added

- `allspark/data/models.yaml` — single source of truth for the
  tier→model mapping, GGUF download URLs (HF + hf-mirror), and per-
  model resource requirements. Replaces three previously-hardcoded
  dicts (`hardware.LLM_MODEL_MAP`, `web_ui.MODEL_DOWNLOAD_URLS`/
  `MIRROR_DOWNLOAD_URLS`, `init_wizard.MODEL_DOWNLOAD_URLS`/
  `MIRROR_URLS`).
- `allspark.services.model_registry` — typed loader for `models.yaml`
  exposing `get_recommended_model()`, `get_model()`, `list_models()`,
  and `resolve_model_name()` with override priority
  env > config.toml > yaml default.
- LLM model override entry points: the `ALLSPARK_LLM_MODEL`
  environment variable, the `[llm] model = "..."` key in
  `~/.allspark/config.toml`, or dropping a custom `.gguf` directly
  into `~/.allspark/models/`. All three documented in
  `docs/CONFIGURATION.md`.
- Override catalog in `models.yaml`: `deepseek-v4-flash` (284B/13B
  MoE, ≥192GB), `deepseek-v4-pro` (1.6T/49B MoE, ≥1TB),
  `deepseek-r1-distill-qwen-14b` (reasoning-mode option for
  Comfortable+), `qwen3-coder-30b-a3b-instruct-q4` (tool-use option
  for Flagship). None are defaults — strict per-tier RAM-fit policy
  keeps 32GB Flagship users from auto-OOM.

### Changed

- Default LLMs upgraded from Qwen2.5 (Sept 2024) to Qwen3 series
  across all five tiers:
    - Phantom (≥2GB): Qwen3-1.7B-Instruct-Q4_K_M (was Qwen2.5-1.5B)
    - Minimum (≥4GB): Qwen3-4B-Instruct-Q4_K_M (was Qwen2.5-3B)
    - Recommended (≥8GB): Qwen3-8B-Instruct-Q4_K_M (was Qwen2.5-7B)
    - Comfortable (≥16GB): Qwen3-14B-Instruct-Q4_K_M (unchanged size)
    - Flagship (≥32GB): Qwen3-32B-Instruct-Q4_K_M (was Qwen2.5-72B —
      72B-Q4 needed 40GB+ which exceeded the tier RAM threshold and
      auto-OOM'd many users; 32B fits the budget honestly)
- `infrastructure.hardware.LLM_MODEL_MAP` is retained for backward
  compatibility but now sources its identifiers from `models.yaml`.
  The `compute_feature_flags()` function delegates LLM selection to
  the registry and respects override env/config.
- `init_wizard._choose_other_model()` and `web_ui` model APIs read
  the catalog dynamically from `model_registry`. Adding a new model
  is now a yaml change, not a code change.

### Documentation

- `docs/CONFIGURATION.md` adds a "Default LLM per hardware tier"
  section with the upgraded mapping, an "Overriding the default
  model" how-to, and an "Override catalog (advanced)" reference for
  the V4 / R1-Distill / Coder lineup.

## [1.0.1] - 2026-06-17

Maintenance release. Closes the v1.0.0 regression backlog (B-1..B-22),
pays off the first half of the mypy typing roadmap, and lands a CI
import-time benchmark guardrail. No public API changes.

### Fixed

- **Web/REST contracts** (B-1, B-3, B-4, B-6, B-7, B-8): `POST
  /api/experience` now returns 400 for missing fields instead of
  crashing 500; reset endpoints surface the rejection reason; community
  governance endpoints accept JSON body uniformly with the rest of the
  surface; `error_response()` returns the proper HTTP status code (~30
  call sites); enabling a non-existent module rejects instead of
  silently succeeding; language endpoint accepts `lang`/`language`
  consistently.
- **i18n persistence and rendering** (B-2, B-9, B-10, B-12, B-15, B-19,
  B-20, B-22): titles persist as i18n keys (not translated strings) so
  language switches re-render correctly; init wizard auto-detects
  browser/system language; web JS templates route every visible string
  through the i18n table (52 new keys, both locales); daily briefing
  emits a localized "[no English version]" hint instead of a bare
  language tag when a knowledge entry is monolingual; psych state and
  resource-mode badges resolve through the i18n table; SKF route
  errors are localized; network/vision unavailability returns a
  friendly degraded card.
- **Data semantics** (B-5, B-13, B-14, B-16): the 9999h "infinite"
  power-runtime sentinel no longer leaks to the UI; diary refuses
  duplicate (date, emotion, content) inserts; goal creation refuses
  duplicate titles; resource status no longer reports SUFFICIENT when
  consumption is zero / unknown.
- **UX polish** (B-11, B-17, B-18, B-21): web replaces `alert(e)`-on-
  exception with a friendly notify wrapper; CLI help columns are now
  uniformly aligned; GPS coordinates are validated to lat ∈ [-90, 90]
  / lng ∈ [-180, 180]; goal/task lists separate items with a thin rule
  for legibility.

### Added

- `scripts/migrate_i18n_legacy.py` — one-shot migration that reverse-
  maps persisted bilingual title strings back to i18n keys for tasks /
  goals / timeline_events tables, and deduplicates timeline rows the
  pre-B-2 bug created twice. Default mode is dry-run; `--apply`
  commits in a single transaction. Tracks SHA-39.
- `scripts/bench_import.py` — import-time module benchmark, runs in CI
  as an advisory step. Soft budget defaults to 600 ms; overrun emits
  `::warning::` and stays green. Promote to `--hard-fail` once the
  floor is stable. Tracks SHA-30.
- `docs/MANUAL_CHECKLIST.md` — verification checklist covering what
  `pytest tests/` cannot: live LLM, voice/vision hardware, multi-node
  spark networking, Docker elastic deployment, long-running scheduler.
  Tracks SHA-36.

### Changed

- mypy typing debt: paid off five categories (`list-item`,
  `var-annotated`, `return-value`, `call-overload`, `index`) — 29
  errors total, on top of the 37 `union-attr` errors retired right
  before v1.0.0. The `[tool.mypy] disable_error_code` allowlist drops
  from 9 entries to 4 (`arg-type`, `assignment`, `attr-defined`,
  `operator`). 91 known errors remain, scheduled by
  `docs/TYPING_ROADMAP.md`. Tracks SHA-29.
- CI workflow: `pytest tests/` step removed (the directory is
  intentionally gitignored, see SHA-28); the workflow now exports
  `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24` to suppress the Node.js 20
  deprecation warning.
- `AUDIT_*.md` is now gitignored alongside the other internal status
  docs (PRD/PROGRESS/ARCHITECTURE/REVIEW-PLAN/TECH-DECISIONS/CLAUDE).

## [1.0.0] - 2026-06-13

First public stable release. Builds on the v0.7 architecture refactor
with security hardening, sdist hygiene, and a documented engineering
roadmap. No breaking changes for existing v0.7 users.

### Added

- Open-source contribution, security, configuration, release, and code-of-conduct documentation.
- `MANIFEST.in` to keep `tests/` out of the published sdist and to ship
  the public docs (CHANGELOG, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT,
  docs/) inside it.
- `docs/TYPING_ROADMAP.md` recording the 157-error mypy debt with a
  10-step repayment plan against `disable_error_code`.
- `docs/BENCHMARKS.md` capturing an import-time baseline for 27 modules
  (sum-of-means 158.9 ms; slowest is `core.i18n` at 149.7 ms).
- `docs/adr/` with ADR 001 (spark-net encryption), ADR 002 (Tier 3
  knowledge review), and ADR 003 (SKF package signing) — all formally
  Deferred to v2.0+.
- PyPI/GitHub project metadata.

### Changed

- Bumped to v1.0.0 across `pyproject.toml`, `allspark/__init__.py`,
  `README.md`, `README_CN.md`. Trove classifier moved to
  `Development Status :: 5 - Production/Stable`.
- Synchronized internal status documents around the current codebase
  (537 tests across 26 files).
- Clarified that mypy is CI-enforced but still uses historical
  typing-debt allowlists.
- `TECH-DECISIONS.md §4` now links to `docs/adr/` instead of carrying
  inline TBD bullets.

### Security

- Hardened SKF Web API path handling: `/api/skf/{info,export,import}`
  now confine the `path` query parameter to `~/.allspark/skf/` and
  reject attempts to escape the directory (previously these endpoints
  accepted arbitrary filesystem paths — a path-traversal vulnerability).
- Verification endpoints `/api/verify/{entry,batch}` now obtain
  `KnowledgeVerifier` through the ServiceContainer instead of
  constructing it inline, matching the project's dependency-injection
  policy.
- Source distribution no longer ships the `tests/` tree (was leaking
  despite `.gitignore` because setuptools default-includes the
  directory).

## [0.7.0] - 2026-05-20

### Added

- ServiceContainer dependency injection.
- Command Pattern command layer with automatic discovery.
- ApplicationBootstrap startup orchestration.
- Docker elastic deployment support.
- Externalized i18n locale files with 700+ keys.
- YAML-based knowledge data.
- `py.typed` package marker.

### Changed

- Reduced CLI and Web UI responsibilities after architecture refactor.
- Moved Web UI HTML into templates.
- Cleaned Ruff lint issues.

## [0.6.0] - 2026-05-18

### Added

- Voice interaction framework with optional Whisper STT and pyttsx3 TTS support.
- Voice diary and voice routing foundations.

## [0.5.0] - 2026-05-17

### Added

- GPS manager with manual/sensor positioning and track records.
- Environment assessment with climate, terrain, threat, and opportunity dimensions.
- Resource-environment linkage.

## [0.4.0] - 2026-05-17

### Added

- jieba tokenizer integration.
- Local LLM integration path.
- Experience engine.
- Tier 1-2 knowledge expansion.
- Web UI.
- Daily briefing, survival timeline, diary, offline weather, and psychology modules.

## [0.3.0] - 2026-05-16

### Added

- Hardware detection and tiering.
- Initialization wizard.
- Modular loading.
- Goal system.
- Three-level reset manager.
- Initial automated test suite.

## [0.2.0] - 2026-05-15

### Added

- Chinese/English i18n framework.
- Five-mode personality system.
- English knowledge content.

### Changed

- Addressed Beta 1.0 review findings.

## [0.1.0] - 2026-05-14

### Added

- MVP rule engine.
- Tier 0 survival knowledge.
- Five-dimensional resource monitoring.
- CLI interface.
- Survival assessment, task planning, personality system, and map support.
