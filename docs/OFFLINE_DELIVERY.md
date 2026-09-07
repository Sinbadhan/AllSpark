# Offline Delivery

AllSpark's supported core loop does not require a model or a network connection.
This document defines an optional portable artifact that lets an operator run
that loop on a clean target Mac without Python, pip, Git, or Xcode. The
canonical open-source release artifacts remain the source archive and wheel.

## Current Target

The first reproducible portable target is macOS on Apple Silicon
(`macos-arm64`). Source and wheel installs are supported open-source release
paths. Windows packaging and Windows + NVDA remain Testing. Linux appliance
images remain Experimental until a target distribution and real-device
evidence are selected.

## Build

Build on the same target architecture. PyInstaller is not a cross-compiler.

```bash
python3.12 -m venv .venv-delivery
.venv-delivery/bin/python -m pip install --require-hashes -r requirements/bootstrap-macos-arm64-py312.lock
.venv-delivery/bin/python -m pip install --require-hashes --no-build-isolation -r requirements/release-macos-arm64-py312.lock
.venv-delivery/bin/python -m build --no-isolation
.venv-delivery/bin/python -m pip install --no-deps dist/*.whl
.venv-delivery/bin/python scripts/verify_release_dependencies.py --lock requirements/release-macos-arm64-py312.lock --output /tmp/allspark-release-evidence
.venv-delivery/bin/python scripts/build_offline_bundle.py build
```

The official portable input lock targets **macOS arm64 / CPython 3.12.14**.
It is not a lock for Intel, Linux, Windows or another Python minor. Generic
source/wheel version ranges remain in `pyproject.toml`; this does not broaden
the validated hardware matrix. Setuptools is explicitly locked to 84.0.0;
the backend lower bound is 77.0.3 for the declared PEP 639 metadata.

To refresh inputs, use a clean target environment and pip's resolver:

```bash
python -m pip install --dry-run --ignore-installed --report /tmp/release-resolution.json ".[delivery]" -r requirements/release-tools.in
python scripts/lock_release_inputs.py /tmp/release-resolution.json
```

Review the resulting version/hash diff, then repeat clean runtime and delivery
installs, the vulnerability/license/schema gates, and bundle verification.
The runtime lock excludes audit/freezer tooling; its separate clean venv must
install the built wheel (not editable source) and pass CLI/Web smoke from
outside the repository. Source artifacts such as jieba use the locked backend
with build isolation disabled. A lock and a zero-known-vulnerability scan are
dated engineering evidence, not a claim that dependencies are vulnerability-free.

The command creates a versioned directory and a normalized `.tar.gz` under
`dist/offline/`. It prints the archive SHA256. The archive contains:

- the Python runtime and all required dependencies;
- the AllSpark executable, templates, translations, safety fixtures, and core
  knowledge;
- a file-level `delivery-manifest.json` and `SHA256SUMS`;
- a CycloneDX SBOM, third-party notices, and the exact dependency license texts;
- double-click verify, install, Web launch, CLI launch, rollback, and optional
  model side-load commands.

Assembly is deterministic for an identical frozen payload and
`SOURCE_DATE_EPOCH`. PyInstaller's Mach-O UUID and code-signing data, Developer
ID timestamps, and Apple notarization records can make independent end-to-end
build bytes differ, so AllSpark does not claim bit-for-bit reproducible frozen
executables. Instead, the manifest records the exact source commit, dirty state,
target, release channel, signature state, file hashes, sizes, and modes.
PyInstaller and its hook dependencies are pinned in the `delivery` dependency
group; a release record must retain the build-host OS/Python output and final
artifact checksum. Bundle assembly fails closed when a dependency license is
unknown, and verification requires the SBOM and notices to cover the exact
runtime dependency closure and be included in the integrity manifest. An
open-source Stable release is satisfied by independently
verifiable source/wheel artifacts and, when published, a checksum-verified
portable archive. Signing status must be stated truthfully.

## Optional Signing And Notarization

Developer ID signing and notarization are required only when the project offers
an official Gatekeeper-trusted macOS App or DMG convenience download. They do
not block publication of source, wheel, or a checksum-verified portable archive.
For that optional channel, the release command verifies the portable archive,
creates a signed UDIF DMG, submits it to the notary service, staples the ticket,
and runs Gatekeeper assessment:

```bash
.venv-delivery/bin/python scripts/build_offline_bundle.py build \
  --release \
  --sign-identity "Developer ID Application: ORGANIZATION (TEAMID)" \
  --notary-profile allspark-notary
```

`--release` fails closed if either credential reference is absent. Certificates,
keys, Apple credentials, and notary profiles must never enter the repository or
the delivery archive. Release builds also fail when the Git worktree is dirty;
internal RC manifests explicitly record a dirty source state instead of
pretending the commit alone identifies their contents.

The `.tar.gz` is a verifiable portable distribution and provenance artifact.
When a signed DMG is offered, do not submit the tar to `notarytool`; Apple's
supported upload containers are ZIP, flat PKG, and UDIF DMG.

## Offline Acceptance Run

1. Transfer the portable archive and its published SHA256 to a clean Apple
   Silicon Mac. If testing the optional signed channel, transfer the stapled DMG.
2. Disconnect every network interface.
3. Verify the published SHA256, extract the portable archive, and run
   `Verify AllSpark.command`. For the optional signed channel, open the DMG
   instead.
4. Run `Install AllSpark.command`, then
   `~/Applications/AllSpark/Launch AllSpark Web.command`.
5. Complete the immediate-danger check, minimum assessment, and confirmation of
   the first 24-hour plan while recording elapsed time. Five minutes remains
   an unvalidated product target; the current AI preflight estimates 7-10
   minutes for a non-technical user and cannot replace the SHA-246 human pilot.
6. Quit, relaunch, record one task outcome, and confirm reassessment works.
7. Install the previous candidate, reinstall the new candidate, run
   `Roll Back AllSpark.command`, and confirm the previous executable becomes
   current without changing `~/.allspark` data.

Record the artifact SHA256, manifest, target hardware/OS, elapsed time, result,
and any recovery observations in Feishu AS-13 (historical key SHA-245). Per the
2026-09-07 user decision, internal acceptance archives stay local and need not
be uploaded. This removes only the upload dependency, not the clean-device
gate. An automated build or local smoke run does not replace this acceptance.

## Optional Models And Content

Core knowledge is embedded and covered by the delivery manifest. No GGUF is
required for the supported flow.

Optional model weights remain Experimental and are delivered separately due to
size and licensing. A model sidecar must contain these three files together:

- `MODEL.gguf`
- `MODEL.gguf.sha256`, whose first field is the expected SHA256
- `MODEL.gguf.metadata.json`, recording model name/version, source URL, license,
  file size, compatible backend, and the person/date that approved distribution

Drag the GGUF onto `Install Optional Model.command`. It copies nothing unless
all three files exist and the checksum matches. A successful checksum proves
file integrity, not model quality, safety, licensing, or Stable support.

## Upgrade, Rollback, And Data

Installations are side by side under
`~/Applications/AllSpark/versions/`. The installer verifies the artifact before
copying it and atomically switches `current`; the former target becomes
`previous`. Rollback validates that the previous executable exists before
switching the pointer.

Runtime data stays under `~/.allspark`. Upgrades and rollback do not erase or
downgrade that data. A release that changes the database schema must add an
explicit forward migration, backup, and downgrade compatibility decision before
shipping. Local data is owner-restricted on validated POSIX paths but is not
application-layer encrypted; see `docs/PRIVACY.md`.
