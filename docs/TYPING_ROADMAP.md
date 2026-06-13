# Typing Debt Roadmap

> **Status:** v1.0 ships with the historical mypy error-code allowlist
> intact. CI runs mypy and fails on any *new* category not on the
> allowlist, but ten existing categories are silenced. This document
> records the actual debt and the agreed-upon repayment order.

## 1. Current allowlist

`pyproject.toml [tool.mypy] disable_error_code` currently silences:

```
arg-type, assignment, attr-defined, call-overload, index,
list-item, operator, return-value, union-attr, var-annotated
```

`ignore_missing_imports = true`, `no_implicit_optional = false`,
`warn_return_any = false`, `check_untyped_defs = false` are also set;
those are configuration choices, not debt categories.

## 2. Measured debt (2026-06-13)

Captured by temporarily emptying `disable_error_code` and running:

```bash
mypy allspark/ --ignore-missing-imports 2>&1 | grep "error:"
```

| Error code        | Count | Notes |
|-------------------|------:|-------|
| `union-attr`      |    37 | Optional attribute access without narrowing |
| `attr-defined`    |    32 | Mostly third-party objects with no stubs |
| `operator`        |    22 | `int + None`, `str + bytes`, etc. |
| `arg-type`        |    21 | Wider input types than callee accepts |
| `assignment`      |    16 | Re-binding to a stricter type |
| `index`           |    10 | Subscripting on `Optional`/`Any` |
| `var-annotated`   |     7 | Container literals lacking annotations |
| `return-value`    |     6 | Return type does not match signature |
| `call-overload`   |     4 | Wrong overload selected |
| `list-item`       |     2 | Heterogeneous list elements |
| **Total**         | **157** | |

Hot spots:

| File | Errors |
|------|------:|
| `allspark/services/environment.py` | 35 |
| `allspark/commands/ai.py` | 16 |
| `allspark/services/rule_engine.py` | 10 |
| `allspark/commands/knowledge.py` | 10 |
| `allspark/adapters/init_wizard.py` | 10 |
| `allspark/services/skf_manager.py` | 9 |
| `allspark/services/reset_manager.py` | 7 |

## 3. Repayment order

Easiest first — categories that usually require local annotation
fixes rather than a structural rethink:

| Step | Code            | Why this order |
|-----:|-----------------|----------------|
|  1   | `list-item`     | 2 errors, mechanical fix |
|  2   | `var-annotated` | 7 errors, add literal annotations |
|  3   | `return-value`  | 6 errors, signature alignment |
|  4   | `call-overload` | 4 errors, often a missing cast |
|  5   | `index`         | 10 errors, narrow Optional with `assert`/guard |
|  6   | `assignment`    | 16 errors, refactor variable reuse |
|  7   | `arg-type`      | 21 errors, narrow callers or widen callee |
|  8   | `operator`      | 22 errors, often Optional arithmetic |
|  9   | `attr-defined`  | 32 errors, may need `cast` or stubs |
| 10   | `union-attr`    | 37 errors, the deepest debt; tackle last |

## 4. Schedule

- **v1.0:** allowlist preserved as-is. No regression beyond steps 1–10.
- **v1.1+:** repay one or two steps per maintenance cycle. Each PR
  removes the relevant code from `disable_error_code` and either fixes
  every error or fails CI. No "fix one, silence one" patches.
- **v2.0:** target zero entries in `disable_error_code` and lift
  `check_untyped_defs = true` once steps 1–10 are clear.

## 5. Acceptance criteria for each step

1. Remove the chosen code from `disable_error_code`.
2. `mypy allspark/ --ignore-missing-imports` exits 0.
3. `pytest tests/` exits 0.
4. CI green on Python 3.10 / 3.11 / 3.12.
5. Update §2 of this file (counts only — drop the row when it hits 0).
