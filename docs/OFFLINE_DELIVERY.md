# Offline Delivery

AllSpark's supported core loop does not require a model or a network connection.
This document defines the release artifact that lets a non-developer install and
run that loop on a clean target Mac without Python, pip, Git, or Xcode.

## Current Target

The first reproducible delivery target is macOS on Apple Silicon
(`macos-arm64`). Python-source and wheel installs remain useful for development,
but they are not the non-developer Stable installation path. Windows packaging
and Windows + NVDA remain Testing. Linux appliance images remain Experimental
until a target distribution and real-device evidence are selected.

## Build

Build on the same target architecture. PyInstaller is not a cross-compiler.

```bash
python3 -m venv .venv-delivery
.venv-delivery/bin/pip install --upgrade pip
.venv-delivery/bin/pip install -e ".[delivery]"
.venv-delivery/bin/python scripts/build_offline_bundle.py build
```

The command creates a versioned directory and deterministic `.tar.gz` under
`dist/offline/`. It prints the archive SHA256. The archive contains:

- the Python runtime and all required dependencies;
- the AllSpark executable, templates, translations, safety fixtures, and core
  knowledge;
- a file-level `delivery-manifest.json` and `SHA256SUMS`;
- double-click verify, install, Web launch, CLI launch, rollback, and optional
  model side-load commands.

Unsigned RC reproducibility is checked by rebuilding with the same clean source
commit, target toolchain, and `SOURCE_DATE_EPOCH`; those inputs must produce the
same assembled archive. Developer ID timestamps and Apple notarization records
are external release evidence and may make signed bytes differ. The manifest records
the exact source commit, target, release channel, signature state, file hashes,
sizes, and modes. PyInstaller and its hook dependencies are pinned in the
`delivery` dependency group; a release record must also retain the build-host
OS/Python output and final archive checksum.

## Signing And Notarization

An unsigned bundle is an internal RC proof only. A Stable macOS artifact must
use an Apple Developer ID Application identity and a configured notarytool
keychain profile. The release command first verifies the reproducible tar, then
creates a signed UDIF DMG, submits that Apple-supported container to the notary
service, staples the ticket to the DMG, and runs Gatekeeper assessment:

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

The `.tar.gz` is reproducibility evidence and an internal transfer format. The
signed, notarized, stapled `.dmg` is the Stable end-user artifact. Do not submit
the tar to `notarytool`; Apple's supported upload containers are ZIP, flat PKG,
and UDIF DMG.

## Offline Acceptance Run

1. Transfer the stapled DMG and its published SHA256 to a clean Apple Silicon Mac.
2. Disconnect every network interface.
3. Open the DMG and run `Verify AllSpark.command`.
4. Open `Install AllSpark.command`, then
   `~/Applications/AllSpark/Launch AllSpark Web.command`.
5. Complete the immediate-danger check, minimum assessment, and confirmation of
   the first 24-hour plan in less than five minutes.
6. Quit, relaunch, record one task outcome, and confirm reassessment works.
7. Install the previous candidate, reinstall the new candidate, run
   `Roll Back AllSpark.command`, and confirm the previous executable becomes
   current without changing `~/.allspark` data.

Attach the artifact SHA256, manifest, target hardware/OS, elapsed time, result,
and any recovery observations to SHA-245. An automated build or local smoke run
does not replace this clean-device acceptance run.

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
