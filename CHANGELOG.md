# Changelog

All notable changes to AllSpark are documented here.

This project follows the spirit of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Version numbers are tracked in `pyproject.toml` and `allspark/__init__.py`.

## [Unreleased]

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
