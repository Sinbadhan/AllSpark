# Release Checklist

Use this checklist before tagging or publishing an AllSpark release.

## 1. Confirm scope

- Confirm the release goal and version number.
- Confirm no v2.0+ work is accidentally included in a maintenance release.
- Review `CHANGELOG.md` and update the `Unreleased` section.
- For v1.0.3, confirm the Stable boundary is desktop PROCESS mode plus local
  core workflows. Docker/INTEGRATION, real LLM/GPU, voice, vision, Raspberry Pi
  hardware, sensors/power/GPS, cross-host networking and removable-media
  disaster recovery remain Experimental unless new real-environment evidence
  is attached to SHA-33.
- Confirm Bluetooth and Wi-Fi Direct are not advertised as transports; v1.0.3
  implements LAN TCP transport and radio availability detection only.
- Confirm the accessibility boundary is macOS VoiceOver for the validated core
  Web flow. Windows + NVDA remains Testing until real-environment
  evidence passes and must not be advertised as Stable.
- Confirm psychology and crisis support remain Experimental. They may not be
  advertised as clinically validated or promoted until SHA-260 contains a
  traceable review from a qualified mental-health or crisis-intervention expert.

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

Until the matching tag exists, the package version is a release candidate:
keep its changes under `Unreleased`, mark public docs as Release Candidate, and
do not use the Production/Stable package classifier. Creating the tag, moving
the changelog section, and promoting the classifier are one release operation.

## 3. Run local quality checks

```bash
ruff check allspark/ tests/
mypy allspark/ --ignore-missing-imports
python3.10 -m pytest -q --tb=short --cov=allspark --cov-branch \
  --cov-report=term-missing --cov-report=json:coverage.json
python3.10 scripts/check_coverage.py --coverage-json coverage.json
python3 tests/regression/run_all.py
python3 scripts/bench_import.py --check --hard-fail
```

On a real macOS/Linux candidate installation, also verify that managed data,
backup, and snapshot directories are `0700`, while the database, WAL/SHM,
backups, snapshots, and metadata are `0600`. Keep Windows ACL support in Testing
until a real Windows run is attached; see `docs/PRIVACY.md`.

Do not lower coverage or collection floors to make a release pass. Record the
exact pytest, coverage, regression, and benchmark output in the release PR.
Python 3.10 is the canonical coverage environment; CI still runs the complete
test suite and collection gate independently on Python 3.11 and 3.12.
Run §1 of `docs/MANUAL_CHECKLIST.md` and attach the keyboard, macOS VoiceOver,
and 200% browser-zoom evidence to the release PR. Attach Windows + NVDA evidence
only when promoting that compatibility out of Testing.

Exercise Web first-run recovery in real Chrome: interrupt the process after a
partial assessment, restart it, confirm the UI labels the recovered state as
unpublished, continue without losing fields, then separately verify the
two-step discard path. Confirm browser storage contains no draft, a failed
publish leaves no partial official rows, retry creates no duplicate gap tasks,
and a successful publish removes the draft. Exercise the CLI transaction
failure path separately; CLI does not consume a Web partial draft.

## 4. Check package metadata

```bash
python3 -m build
python3 -m twine check dist/*
```

If `build` or `twine` is not installed, install them in a release environment rather than adding them as runtime dependencies.

## 4A. Build the offline desktop artifact

For the current non-developer target, follow `docs/OFFLINE_DELIVERY.md` on an
Apple Silicon macOS build host. A Stable artifact must be built with
`--release`, Developer ID signed, notarized, and then verified from its archive:

```bash
python scripts/build_offline_bundle.py build --release \
  --sign-identity "Developer ID Application: ORGANIZATION (TEAMID)" \
  --notary-profile allspark-notary
python scripts/build_offline_bundle.py verify dist/offline/*.tar.gz
xcrun stapler validate dist/offline/*.dmg
```

- Record reproducibility archive SHA256, end-user DMG SHA256, artifact ID,
  source commit, target, size, signature, notarization and stapler result in
  SHA-245 and the GitHub Release.
- Run the clean-device, disconnected acceptance flow in
  `docs/OFFLINE_DELIVERY.md`; CI's unsigned bundle is only a reproducibility and
  launch gate.
- Confirm core knowledge is present and no model is required.
- Verify install, failed-checksum no-write behavior, side-by-side upgrade and
  rollback without changing `~/.allspark` data.
- Optional model sidecars must include checksum and distribution metadata;
  checksum success does not promote LLM support out of Experimental.

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
- `docs/PRIVACY.md` reflects the current data inventory, plaintext storage,
  unpublished initialization draft, deletion limits, and encryption/Windows
  boundaries.
- `docs/REAL_WORLD_VALIDATION.md` separates verified automation from hardware
  that was not exercised in this release.
- `CHANGELOG.md` has release notes for the new version.

## 7. Confirm release scope and external evidence

- SHA-158 contains the final audit comment and no unresolved P0/P1 blocker.
- SHA-158 Current baseline and the latest Linear project status update name the
  same exact main commit, test counts, open-item counts and release health.
- Hardware-dependent SHA-33 rows are either evidenced for this release or
  explicitly excluded from the supported release scope.
- SHA-180 single-host multiprocess evidence passes. SHA-179 and the external
  media portion of SHA-181 may stay open only when their capabilities are
  explicitly Experimental and excluded from Stable support.
- The RC pull request is green on all Python versions, including the clean-wheel
  smoke matrix and real-Chrome SKF XSS gate.
- Record the successful workflow run for the exact release-candidate commit.
  Historical failed runs do not describe the current HEAD; the selected run
  must complete every required job without Node runtime deprecation annotations.
- SHA-152 contains completed keyboard-only, macOS VoiceOver, and 200% zoom
  evidence. Automated DOM tests and screenshots do not substitute for the
  VoiceOver assistive-technology run. Windows + NVDA is explicitly recorded as
  `not_run`/Testing and excluded from the v1.0.3 Stable accessibility claim.
- Enforcing CSP is present on HTML, API, authentication-error and bootstrap
  responses; all rendered scripts carry the matching per-request nonce,
  `script-src-attr 'none'` is active, and the seven-page Chrome violation gate
  passes for the exact candidate commit.
- SHA-260 confirms deterministic self-harm safety triage runs before rule/LLM
  chat, makes no unsupported notification or recording claim, and includes the
  external expert-review state. Automation is not expert sign-off.

## 8. Tag and publish

Only after checks pass:

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

The version in `pyproject.toml` and `allspark/__init__.py`, the changelog release
heading, Git tag and GitHub Release must match exactly. Never add a dated
changelog release heading before its tag exists.

Create a GitHub Release using the matching `CHANGELOG.md` section.

Publish to PyPI only from a clean release environment and only after maintainer confirmation.

## 9. Post-release

- Confirm the GitHub Release renders correctly.
- Confirm installation instructions still work.
- Move released changelog entries out of `Unreleased`.
- Open follow-up issues for deferred items instead of mixing them into the release branch.
