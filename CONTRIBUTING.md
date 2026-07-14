# Contributing to AllSpark

Thank you for helping improve AllSpark. This project is an offline-first survival AI system, so contributions should favor reliability, clarity, local operation, and safe failure modes over novelty.

## Ways to contribute

- Report bugs or confusing behavior through GitHub Issues.
- Submit small pull requests with a clear problem statement and verification notes.
- Improve documentation, configuration guidance, and release hygiene.
- Expand Tier 0-3 knowledge entries with clear sources and risk notes.
- Improve translations and i18n coverage.

## Development setup

```bash
pip install -e ".[dev]"
```

Run the app locally:

```bash
python3 -m allspark
python3 -m allspark --web
```

## Quality checks

Run these before opening a PR:

```bash
ruff check allspark/ tests/
mypy allspark/ --ignore-missing-imports
python3 -m pytest tests/ -v --tb=short
```

`mypy` is enforced in CI with `check_untyped_defs = true` and no disabled error-code categories — it runs clean. Historical typing debt was cleared in SHA-29/40.

## Tests and CI

CI runs `ruff check`, `mypy`, and the complete tracked `pytest` suite on Python
3.10/3.11/3.12. The canonical Python 3.10 coverage job requires at least 75%
total line coverage, at least 90% branch coverage on the eight SHA-151
critical-path modules, and a ratcheted collection-count floor. Python 3.11 and
3.12 still run the complete suite and collection gate; coverage is collected
once because coverage.py does not consistently trace Starlette TestClient
portal threads across runtimes. CI also builds and installs a clean wheel on
all supported Python versions and runs the import benchmark in advisory mode.
The workflow and `scripts/check_coverage.py` are the source of truth for exact
thresholds; do not copy a transient test count into documentation.

## Pull request guidelines

- Keep PRs small and focused. Separate bug fixes, refactors, and feature work.
- Explain what changed, why it changed, and how it was verified.
- Update docs when behavior, configuration, commands, or release process changes.
- Do not include runtime data, local models, databases, logs, secrets, or personal survivor data.
- Avoid broad rewrites unless there is a clear architectural reason and tests cover the migration.

## Coding conventions

- User-visible text must go through `t()` and locale YAML files.
- Do not add bare `print()` calls in production code. CLI/Web display code may use Rich `console.print`; services and infrastructure should use `logging.getLogger(__name__)`.
- Services should be obtained through `ServiceContainer` with `container.get(...)`. Avoid manually constructing services in routes or commands unless there is a documented reason.
- New commands belong in `allspark/commands/`, inherit `BaseCommand`, and should work with automatic discovery.
- Knowledge content belongs in `allspark/data/knowledge/*.yaml`, loaded through the existing knowledge loader. Do not hard-code new knowledge dictionaries in Python.

## Knowledge base contributions

Survival knowledge can be dangerous if wrong or ambiguous. For knowledge entries:

- Prefer conservative, verifiable guidance.
- Include source context where possible.
- Mark uncertainty and risk clearly.
- Avoid instructions that require unavailable equipment unless alternatives are provided.
- Do not add medical, chemical, electrical, or defensive guidance without strong review and safety caveats.

## Scope boundaries

Large v2.0+ items such as personality evolution, signed knowledge packages, full hardware validation, LoRa/Bluetooth disaster channels, and professional intervention protocols should be discussed before implementation. Do not mix them into small cleanup PRs.
