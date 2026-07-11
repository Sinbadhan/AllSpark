# Release Checklist

Use this checklist before tagging or publishing an AllSpark release.

## 1. Confirm scope

- Confirm the release goal and version number.
- Confirm no v2.0+ work is accidentally included in a maintenance release.
- Review `CHANGELOG.md` and update the `Unreleased` section.

## 2. Update version references

Check and update these together:

- `pyproject.toml`
- `allspark/__init__.py`
- `README.md`
- `README_CN.md`
- `CHANGELOG.md`

Version bumps follow semantic versioning. The project is on the 1.0.x line;
do not bump to a new minor/major unless the maintainer explicitly approves the
release scope and the audit gate (SHA-158) is green.

## 3. Run local quality checks

```bash
ruff check allspark/ tests/
mypy allspark/ --ignore-missing-imports
python3 -m pytest tests/ -v --tb=short
```

If mypy fails after tightening configuration, either fix the typed code in the same focused change or restore the allowlist and document the remaining debt.

## 4. Check package metadata

```bash
python3 -m build
python3 -m twine check dist/*
```

If `build` or `twine` is not installed, install them in a release environment rather than adding them as runtime dependencies.

## 5. Check repository hygiene

Verify no sensitive or generated files are staged:

- runtime data under `~/.allspark/`
- SQLite databases
- logs
- local model weights
- backups and snapshots
- `.env` files
- keys, certificates, or credentials
- `dist/`, `build/`, and `*.egg-info/`

## 6. Review documentation

- `README.md` and `README_CN.md` have current version and links.
- `CONTRIBUTING.md` has current development commands.
- `SECURITY.md` has a valid reporting path.
- `docs/CONFIGURATION.md` reflects actual configuration behavior.
- `CHANGELOG.md` has release notes for the new version.

## 7. Tag and publish

Only after checks pass:

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

Create a GitHub Release using the matching `CHANGELOG.md` section.

Publish to PyPI only from a clean release environment and only after maintainer confirmation.

## 8. Post-release

- Confirm the GitHub Release renders correctly.
- Confirm installation instructions still work.
- Move released changelog entries out of `Unreleased`.
- Open follow-up issues for deferred items instead of mixing them into the release branch.
