# Typing Roadmap

> **Status:** v1.0.3 has paid down the historical mypy error-code allowlist.
> `pyproject.toml [tool.mypy]` no longer uses `disable_error_code`, and the
> regular project check is clean:
>
> ```bash
> mypy allspark/ --ignore-missing-imports
> ```

## 1. Current Policy

The current CI-oriented mypy policy is intentionally pragmatic:

- `ignore_missing_imports = true`
- `no_implicit_optional = false`
- `warn_return_any = false`
- `check_untyped_defs = false`
- zero `disable_error_code` overrides

This means mypy now catches regular typed-surface regressions without hiding
known categories. The next tightening step is to type-check untyped function
bodies.

## 2. Remaining Strictness Debt

Measured on 2026-06-24:

```bash
mypy allspark/ --ignore-missing-imports --check-untyped-defs
```

| Scope | Count | Notes |
|-------|------:|-------|
| Regular mypy | 0 | Current project gate |
| `--check-untyped-defs` | 13 | Follow-up strictness work |

Hot spots:

| File | Errors |
|------|------:|
| `allspark/adapters/cli.py` | 8 |
| `allspark/bootstrap.py` | 4 |
| `allspark/services/voice.py` | 1 |

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

## 4. Next Steps

1. Fix the 13 `--check-untyped-defs` errors without weakening signatures.
2. Flip `check_untyped_defs = true` in the same change that proves clean.
3. Keep `pytest tests/` and regular mypy green.
4. Later, evaluate `warn_return_any = true` and `no_implicit_optional = true`
   as separate scoped changes.
