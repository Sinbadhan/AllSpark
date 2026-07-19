# P2 Real-World Validation Log

> Last updated: 2026-07-14
> Status: scoped desktop evidence in progress; hardware integrations remain Experimental

## Scope

This log tracks validation that cannot be proven by the restricted desktop
sandbox alone. It separates automated gates from real-world checks that need
local TCP bind, Docker, GPU/LLM runtime, Raspberry Pi GPIO/I2C/SPI, sensors, or
removable storage.

## Automated Baseline

| Gate | Current status | Notes |
| --- | --- | --- |
| `python3 -m mypy allspark/ --ignore-missing-imports` | ready | `check_untyped_defs = true` is enabled in `pyproject.toml`. |
| `python3 -m ruff check allspark/ tests/` | ready | Static style gate. |
| `python3 scripts/bench_import.py --check` | ready (advisory) | Checks both the 600 ms sum-of-means budget and 2000 ms cold wall-clock budget; CI warns on drift. Use `--hard-fail` for a blocking release-environment check. |
| `python3 -m pytest tests/ -q` | ready on local/CI | Full tracked suite on Python 3.10/3.11/3.12; JSON gate enforces ≥75% total line and ≥90% branch on eight critical modules. Exact count: see CI output. |
| `python3 tests/regression/run_all.py` | ready (loopback) | Completes exit 0 on an unrestricted local shell; no `environment_blocked` rows (loopback TCP/uvicorn is no longer blocked). |

## Real-World Matrix

| Area | Status | Required environment | Validation target |
| --- | --- | --- | --- |
| Spark Network TCP exchange | verified (single-host multiprocess) | Two independent Python processes on `127.0.0.1` | Signed happy path, tampered/unsigned rejection, disconnect, same-port restart, configured size rejection and recovery pass in `tests/test_sha180_multiprocess.py`. Cross-host transport remains Experimental. |
| Web regression harness | ready (loopback) | Local shell/CI allowing uvicorn on loopback | `tests/regression/run_all.py` completes all suites exit 0, no `environment_blocked`. |
| Docker graceful deployment | unavailable on audit host | Host with Docker daemon | The audit host has no `docker` command. Automated unavailable/fallback behavior passes; daemon happy/recovery paths remain Experimental (SHA-179). |
| Local LLM runtime | not_run | Machine with target GGUF model and llama-cpp-python backend | Model discovery, load, inference, timeout, and degraded no-model path. |
| GPU acceleration | blocked_by_hardware | CUDA/Metal-capable host matching supported backend | Feature detection and model tier recommendation match hardware profile. |
| Raspberry Pi power monitoring | blocked_by_hardware | RPi + ADC/SPI wiring | Real voltage/current read, manual fallback, low-power warning path. |
| Sensor hub | blocked_by_hardware | I2C/GPIO/Serial sensors and GPS | Temperature/humidity/barometer/GPS readings, stale data handling, manual fallback. |
| Data preservation on real media | software verified; external media environment-blocked | Removable storage or independent filesystem | WAL-consistent atomic snapshot/restore, full SHA-256 verification, valid-SQLite tamper rejection, interrupted creation cleanup and failed-replace reconnect pass. APFS disk-image creation did not complete in this desktop environment, so removable/independent media remains Experimental (SHA-181). |
| Offline web assets | ready | Browser with network disabled | UI remains readable with local CSS/icon fallbacks. |
| Web accessibility | macOS VoiceOver + zoom verified; Windows NVDA Testing | Chrome at 1280 px / 200%; macOS VoiceOver; future Windows + NVDA host | Core dashboard, navigation, resource edit, Repository filter/detail, dialogs and live status pass VoiceOver after `d3c9a6c`; 200% zoom passed after `421d040`. Windows + NVDA is `not_run` and remains Testing (SHA-152). |

## 2026-07-14 Evidence

### SHA-180: single-host independent processes

- Environment: macOS desktop, Apple silicon, Python 3.10.5, loopback TCP only.
- Commit: `01e448b`.
- Gate: `pytest -q tests/test_sha180_multiprocess.py tests/test_sha36_regression.py`.
- Result: 16 passed. The integration starts separate spawned server processes,
  performs shared-secret signing, rejects both bad and missing signatures,
  persists transferred knowledge, detects disconnect, restarts on the same
  port, rejects an over-limit payload and then serves a valid request.
- Boundary: the production constant remains 50 MiB; the process integration
  uses a reduced injected threshold to exercise the same rejection branch
  without allocating 50 MiB in every CI worker.

### SHA-181: snapshot and restore

- Environment: local APFS audit workspace, Python 3.10.5.
- Commit: `b418fc3`.
- Gate: `pytest -q tests/test_data_preservation.py tests/test_sha151_backup.py`.
- Result: 44 passed after the SHA-181 additions. Coverage includes committed
  WAL data, atomic publish, full SHA-256 metadata, legacy 16-character checksum
  compatibility, checksum mismatch before touching the live DB, interruption
  cleanup, stale WAL/SHM cleanup, connection reopening and replace-failure
  recovery.
- Independent-filesystem attempt: two `hdiutil create` attempts remained
  sleeping before project code ran. They were terminated and temporary files
  were removed. This is recorded as environment-blocked, not passed.

### SHA-152: Chrome 200% zoom

- Environment: macOS desktop, Google Chrome, 1280 x 768 browser window, browser
  zoom indicator at 200%.
- Commit: `421d040`.
- Flow: dashboard and status content, mobile navigation, resource editor,
  Repository filter/table/detail dialog, dialog close, and trigger-focus restore.
- Initial result: failed because the fixed mobile navigation overlay did not own
  vertical scrolling, which clipped the Config and Repository actions.
- Fix: the overlay now uses `overflow-y: auto` and contained overscroll, with a
  static regression in `tests/test_sha152_web_a11y.py`.
- Final result: pass. All navigation actions are reachable; tested content and
  controls have no overlap or page-level horizontal scroll; dialogs remain
  operable and use contained vertical scrolling where needed.
- Automated regression: `1128 passed, 6 skipped`; Ruff and mypy pass locally.
- Remaining boundary at the time of this zoom run was real assistive-technology
  evidence; the macOS VoiceOver portion is now recorded below. Windows + NVDA
  remains a testing-stage compatibility track, not a v1.0.3 Stable claim.

### SHA-152: macOS VoiceOver

- Environment: macOS desktop, Google Chrome at 1280 x 768, system VoiceOver
  enabled, isolated local RC database and server.
- Commit: `d3c9a6c`.
- Flow: Dashboard navigation and control names; resource editor title, labelled
  numeric fields, Tab wrap, Escape close and trigger-focus restore; Repository
  filter, result status, native detail trigger, detail dialog focus/trap/close
  restore; About dialog; non-error live status notification.
- Initial result: failed. Repository search re-rendered on every keystroke and
  lost focus after the first character. Repository detail did not take, trap or
  restore focus. Global toast, confirm/prompt and About layers lacked complete
  live-region/dialog semantics. Decorative navigation glyphs polluted names.
- Fix: preserve Repository search focus and cursor, expose native detail
  buttons and live result counts, complete dialog focus lifecycle, mark status
  and error toasts as live regions, and hide navigation glyphs from the
  accessibility tree.
- Final result: pass on the exercised macOS VoiceOver flow. Native accessibility
  state showed clean navigation names, a four-character Repository query with
  focus retained, dialog title/close focus, Tab containment, Escape close,
  trigger restoration, and the live status message. Real-Chrome regression plus
  static/runtime gates: `35 passed` for the focused SHA-152/SHA-212 set.
- Boundary: no Windows + NVDA host was available. That row is `not_run`, remains
  Testing, and is excluded from the v1.0.3 Stable accessibility
  claim until real evidence passes.

## v1.0.3 Support Decision

The Stable candidate scope is desktop PROCESS mode, local core workflows and
the macOS VoiceOver-validated core Web flow. Windows screen-reader compatibility
(NVDA) remains Testing. Docker/INTEGRATION, real model/GPU, voice,
vision, Raspberry Pi hardware,
physical sensors/GPS/power, cross-host networking and removable-media disaster
recovery remain Experimental. Bluetooth and Wi-Fi Direct transports are not
implemented in v1.0.3; channel detection must not be presented as transport.

## 2026-07-20 Internal Re-audit Delta

- Pending knowledge now fails closed at the shared API/CLI/Web output contract;
  review metadata remains visible while actionable content and task creation
  are withheld.
- Immediate-danger routing has dedicated conservative heat, cold, poisoning,
  and choking fact contracts. Source retrieval records and exact hashes are
  bundled; twenty adversarial variants are executed by the audit gate.
- Crisis-support clause scoping, means detection, contact truthfulness, and
  single-line operator configuration have targeted deterministic regression.
- First run, Dashboard, Repository, Executions, task outcomes, plan evidence,
  error states, modal isolation, and assistive labels received code and
  automated contract review.
- The exact current commit, local test/coverage totals, CI run, open Linear
  counts, and release health are maintained only in Linear SHA-158. This file
  intentionally does not duplicate those fast-changing identifiers.
- Real Chrome was not rerun locally in this audit because the available host
  browser path was environment-blocked. No browser-policy workaround was used;
  the exact pushed commit still requires its normal CI/browser evidence, and
  SHA-264 retains the isolated-browser acceptance boundary.
- Decision: **continue Product RC validation; Stable remains No-Go** until the
  external professional reviews, five-person pilot, clean disconnected-device
  delivery, isolated-browser recovery evidence, and exact-commit CI gates are
  complete.

## Remaining External Validation Order

The unrestricted automated baseline and loopback regression are complete. The
remaining work can expand future support claims and is excluded from the
current candidate support boundary:

1. On a post-release hardware-validation track, validate Docker on a
   daemon-enabled host and move SHA-179 out of Experimental only with evidence.
2. Validate LLM model discovery/load/inference with the smallest supported GGUF.
3. Validate Raspberry Pi sensors, power, GPS, cross-host networking and
   removable storage before expanding the public support boundary.
4. Complete independent/removable-media restore evidence and Windows + NVDA
   compatibility testing before promoting those capabilities.
