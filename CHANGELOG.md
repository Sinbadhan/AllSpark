# Changelog

All notable changes to AllSpark are documented here.

This project follows the spirit of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Version numbers are tracked in `pyproject.toml` and `allspark/__init__.py`.

## [Unreleased]

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
