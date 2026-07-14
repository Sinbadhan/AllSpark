# Changelog

All notable changes to AllSpark are documented here.

This project follows the spirit of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Version numbers are tracked in `pyproject.toml` and `allspark/__init__.py`.

## [Unreleased]

### Audit remediation (SHA-158, in progress)

Release-readiness remediation across security, quality, UX, packaging, and
documentation. Linear SHA-158 is the live source for issue status; this section
records shipped behavior and does not claim release readiness before the RC
workflow and supported hardware scope are approved.

**Security (P0):**
- SHA-142: Web auth boundary - token moved out of HTML to httpOnly+SameSite
  cookie; `/login` + `/api/auth/login`; one-time bootstrap (init/complete 410
  after init); middleware always on (loopback local trust, non-loopback gated).
- SHA-147/SHA-196: SKF persistent XSS - import-boundary metadata sanitization,
  output escaping, removal of dynamic row handlers, and a real-Chrome public
  import -> API -> Repository/Dashboard list/detail regression. CSP is currently
  Report-Only; enforcing migration is explicitly deferred to SHA-213.
- SHA-148: Knowledge `expert_verified` signoff schema (reviewer/qualification/
  date/citation/content_hash/signoff_version) + content-hash invalidation;
  142 entries downgraded to field_tested; loader + verifier gating.
- SHA-28: Full test suite tracked in VCS; CI runs it across Python
  3.10/3.11/3.12 and validates clean-wheel installation on the same matrix.

**Quality (P1):**
- SHA-226: Dashboard grid tracks and resource-card contents now shrink and
  wrap predictably instead of inheriting a wide min-content track from the tab
  bar. Phase, mode, resource type, value and status remain visible without a
  main-canvas horizontal scroller at 320/360/390/430px; real-Chrome coverage
  exercises zh/en, unconfigured, critical, sustained and long-unit states.
  The narrow-screen system footer now reserves enough height for both summary
  and health rows instead of clipping the second line.
- SHA-221: Web first run now makes language the first actionable step and
  follows the browser locale for its initial selection. Questionnaire options
  carry stable keys plus zh/en labels, rerender immediately on repeated
  language switches, and preserve entered values across back/forward
  navigation. Native labels and a real skip button provide stable accessible
  names; real-Chrome coverage includes zh/en locale, two switches and L3 reset.
- SHA-218: Config now renders the real about, health, LLM and hardware schemas
  with DOM text APIs instead of undefined page-private escape/i18n helpers.
  LLM state follows `available/model_name`; each endpoint has an independent,
  localized unavailable state so one outage cannot blank the rest of the page.
  A real-Chrome gate checks zero runtime errors, populated normal/unloaded
  fields and a forced four-endpoint degraded rerender.
- SHA-224: Rule-based answers no longer use the stable personality greeting as
  a health claim. API and CLI responses share the same system-health function
  as the Web footer and separately expose current system state, core-resource
  readiness and answer scope (specific, general/verify, no match or generated/
  unverified). The stable style now uses neutral "Standard guidance" wording;
  bilingual API/direct-engine and real-Chrome footer/chat contracts prevent
  degraded systems or generic answers from being success-styled.
- SHA-223: Environment guidance is now evidence-gated across current climate,
  terrain and configured power/water/food data. Missing or stale evidence
  returns an explicit unknown result with no numeric score or exploration
  recommendation; known critical shortages still surface as threats. CLI/API/
  Web expose completeness, source and observation time, with fresh-install,
  partial, stale, complete-data and real-Chrome regression coverage.
- SHA-217: Rule-based survival Q&A now keeps the original user question in
  retrieval and uses intent keywords only as recall expansion. Multi-term title
  coverage promotes specific methods such as battery fire starting; FTS query
  tokens are safely quoted so natural punctuation cannot break search. Explicit
  unknown tool requests return the no-direct-match response instead of a
  generic domain answer, with bilingual RuleEngine and Web API golden coverage.
- SHA-219: Reset scope now comes from one executable matrix shared by CLI and
  Web descriptions. L2 clears diary/FTS, timeline and action plans while
  preserving language, hardware, knowledge and vectors; L3 enumerates SQLite
  top-level application tables so later schema additions cannot silently
  survive a factory reset, then redirects Web clients to canonical first boot.
- SHA-220: Reset audit writes use an explicit migrated schema and record
  accepted, rejected and failed attempts with actor/force reason/backup data.
  The 24-hour cooldown reloads from the latest accepted record after process
  restart; L3 snapshots and clears historical logs before recording itself.
- SHA-150: NL survival Q&A - FTS5 bm25 + title-substring re-rank; 1 main
  answer + 2 related links (not full-text concat); 50+ golden set.
- SHA-149: System health score factors in core capabilities (LLM/modules);
  weather structured rendering (no raw JSON/null).
- SHA-151: JSON-backed gate requires >=75% total line coverage and >=90%
  branch coverage on all eight critical-path modules, plus a ratcheted test
  collection floor. Python 3.10 is the canonical coverage environment while
  Python 3.11/3.12 continue to run the complete functional and collection gates.
- SHA-152: Web a11y - native control semantics, dialog roles, focus traps,
  deterministic focus restoration after async refresh, mobile-nav state/inert
  synchronization, clean navigation names, live status/error announcements,
  Repository filter focus continuity and native detail triggers. The macOS
  VoiceOver core flow is verified; Windows + NVDA remains Testing/Experimental.

**UX (P2):**
- SHA-227: Repository uses an information-first mobile list at 320/390px so
  title, verification, category, tier and the secondary ID remain scannable
  without page-level horizontal scrolling. Desktop and tablet keep the dense
  table, while the file tree now uses native buttons with visible keyboard
  focus and a single `aria-current` item; Enter and Space selection are covered
  by real-browser regression tests in zh and en.
- SHA-225: Hardware tier eligibility is now separate from dependency,
  configuration, runtime and Experimental state in one registry schema shared
  by CLI initialization, `/api/modules` and System. Docker is shown as an
  eligible target until its daemon is verified; the report records the actual
  PROCESS fallback without presenting planned containers as active. System
  exposes dependency/configuration columns, suppresses invalid core-module
  actions and contains the module table in a horizontal scroller on narrow
  screens. Regression coverage includes no-Docker, no-model, missing optional
  dependency, complete-runtime, idle-service and legacy-flags states.
- SHA-222: CLI first run now uses the detected zh/en locale only as a
  non-persistent display default before the first choice; unavailable and
  unsupported locales deterministically fall back to English. Both choices
  remain self-describing as `中文 / Chinese` and `English / 英语`, with a real
  PTY regression proving the English screen is understandable before input.
- SHA-153: Repository browser - search/category/tier/verification/language
  filter + pagination + row detail modal + full ID tooltip.
- SHA-212: Restored the Repository knowledge list after a missing runtime i18n
  mapping caused every normal load to fail; real rendered-JavaScript tests cover
  empty, zero-match, normal, and multi-page states.
- SHA-154: Config page - real read-only view (about+health APIs); removed
  hardcoded configTemplates/SAVED editor chrome.
- SHA-155: CLI cold-start - `render(g.title)` (no marker leak); jieba/
  VectorEngine log noise suppressed.
- SHA-143: Doc/version/CI consistency (workflow and executable gate constants
  are the source of truth) plus `test_doc_consistency` drift guards.
- SHA-180: Spark Network now has independent-process integration coverage for
  signed transfer, tampered and unsigned rejection, disconnect/restart, size
  rejection and recovery. A configured shared secret is enforced rather than
  bypassable by omitting signatures.
- SHA-181: Snapshots use SQLite online backup for WAL consistency, atomic
  publication/replacement, full SHA-256 metadata verification, temp cleanup and
  live-connection recovery after restore failures.
- SHA-182: Experimental status now comes from the server-side module registry
  and is shared by API, Web, CLI and health scoring; the public README defines
  the same scoped support boundary.

**Packaging/hygiene (P3):**
- SHA-144: bench_import - dual metric (sum-of-means micro-bench + wall-clock
  SLO) with independent budgets; `--hard-fail` on either.
- SHA-156: Web dead-entry cleanup (exec-btn -> /executions; removed dead docs
  link; dedup settings icon).
- SHA-157: Package metadata - PEP 639 license; removed deprecated classifier;
  removed unused prompt-toolkit; MANIFEST `*.j2` fix; Python 3.10 `tomli`
  conditional dep; CI clean-wheel smoke matrix (3.10/3.11/3.12).
- SHA-145: Starlette/httpx2 deprecation warning cleared (httpx2 declared).

The macOS VoiceOver announcement gate for SHA-152 is evidenced at `d3c9a6c`.
Windows + NVDA remains an explicit Testing/Experimental compatibility track and
is excluded from the v1.0.3 Stable claim. The v1.0.3 support boundary is desktop
PROCESS mode plus local core workflows and the VoiceOver-validated core Web
flow; SHA-33 remains a post-release
hardware-validation track and cannot expand Stable support without real-world
evidence. SHA-213 (enforcing CSP) is documented follow-up hardening and is not
represented as an active CSP defense in this release.

### Security
- **H1**: Fixed `KnowledgeSigner._derive_key` bug — `getattr(self.db, "_db_path")`
  referenced a non-existent attribute (actual: `db_path`), so every installation
  derived the same HMAC key from the constant `"allspark-default"`. Key is now
  per-node. Cross-node verification still requires a shared secret (v2.0 PKI per ADR 003).
- **H2**: Spark Network TCP exchange server hardening — added
  `SPARKNET_MAX_INCOMING_BYTES` (50 MB) cap to prevent memory-exhaustion DoS;
  a configured `network_shared_secret` now requires a valid signature for every
  incoming entry, including rejection of missing signatures; added
  connection/transfer logging and independent-process regressions.
- **H3**: Web API bearer-token auth — when the Web UI binds a non-loopback host
  (`--host 0.0.0.0` or LAN IP), a bearer token is now required for all `/api/*`
  routes (auto-generated unless `--web-token` is given). `/api/init/*` stays
  open only for one-time bootstrap before initialization. Current behavior uses
  an httpOnly, SameSite cookie and does not inject the credential into HTML.

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
- `CONTRIBUTING.md`: corrected stale mypy/pytest claims and documented the
  reproducible CI, coverage, collection, and clean-wheel gates.

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
