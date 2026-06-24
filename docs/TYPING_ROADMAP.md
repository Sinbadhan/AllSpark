# Typing Roadmap

> **Status:** v1.0.3 has paid down the historical mypy error-code allowlist
> and the `--check-untyped-defs` follow-up debt. `pyproject.toml [tool.mypy]`
> now checks untyped function bodies with no disabled error-code categories:
>
> ```bash
> mypy allspark/ --ignore-missing-imports --check-untyped-defs
> ```

## 1. Current Policy

The current CI-oriented mypy policy is intentionally pragmatic:

- `ignore_missing_imports = true`
- `no_implicit_optional = false`
- `warn_return_any = false`
- `check_untyped_defs = true`
- zero `disable_error_code` overrides

This means mypy catches regular typed-surface regressions and checks the bodies
of untyped functions without hiding known categories.

## 2. Remaining Strictness Debt

Measured on 2026-06-24:

```bash
mypy allspark/ --ignore-missing-imports --check-untyped-defs
```

| Scope | Count | Notes |
|-------|------:|-------|
| Regular mypy | 0 | Current project gate |
| `--check-untyped-defs` | 0 | Enabled in `pyproject.toml` |

## 3. Historical Repayment

| Step | Code | Status |
|-----:|------|--------|
| 1 | `list-item` | Done 2026-06-17 |
| 2 | `var-annotated` | Done 2026-06-17 |
| 3 | `return-value` | Done 2026-06-17 |
| 4 | `call-overload` | Done 2026-06-17 |
| 5 | `index` | Done 2026-06-17 |
| 6 | `assignment` | Done v1.0.3 |
| 7 | `arg-type` | Done v1.0.3 |
| 8 | `operator` | Done v1.0.3 |
| 9 | `attr-defined` | Done v1.0.3 |
| 10 | `union-attr` | Done 2026-06-16 |
| 11 | `check_untyped_defs` | Done 2026-06-24 |

## 4. Next Steps

1. Keep `pytest tests/` and mypy green on every maintenance change.
2. Later, evaluate `warn_return_any = true` and `no_implicit_optional = true`
   as separate scoped changes.
