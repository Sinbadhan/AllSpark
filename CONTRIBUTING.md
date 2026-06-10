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

`mypy` is enforced in CI, but the project still carries historical typing debt isolated by error-code allowlists. Do not present this as fully strict typing unless those allowlists are removed in a focused change.

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
