# P2 Real-World Validation Log

> Last updated: 2026-07-05
> Status: started, not yet completed on real hardware

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
| `python3 scripts/bench_import.py --check` | ready | Current target is the 600 ms soft gate. |
| `python3 -m pytest tests/ -q` | ready on local/CI | Expected unrestricted/local line: 616 passed + 6 skipped. Current restricted sandbox line: 614 passed + 8 skipped. |
| `python3 tests/regression/run_all.py` | ready with environment marker | If localhost TCP bind is forbidden, affected suites report `environment_blocked` instead of a product failure. |

## Real-World Matrix

| Area | Status | Required environment | Validation target |
| --- | --- | --- | --- |
| Spark Network TCP exchange | blocked_by_sandbox | Local shell/CI allowing `127.0.0.1` TCP bind | Two-node request/exchange and knowledge transfer complete without skip. |
| Web regression harness | blocked_by_sandbox | Local shell/CI allowing uvicorn on loopback | `tests/regression/run_all.py` completes all suites without `environment_blocked`. |
| Docker graceful deployment | not_run | Host with Docker daemon | `DockerManager` detects daemon, starts/stops configured services, and preserves PROCESS fallback. |
| Local LLM runtime | not_run | Machine with target GGUF model and llama-cpp-python backend | Model discovery, load, inference, timeout, and degraded no-model path. |
| GPU acceleration | blocked_by_hardware | CUDA/Metal-capable host matching supported backend | Feature detection and model tier recommendation match hardware profile. |
| Raspberry Pi power monitoring | blocked_by_hardware | RPi + ADC/SPI wiring | Real voltage/current read, manual fallback, low-power warning path. |
| Sensor hub | blocked_by_hardware | I2C/GPIO/Serial sensors and GPS | Temperature/humidity/barometer/GPS readings, stale data handling, manual fallback. |
| Data preservation on real media | not_run | Removable storage or separate filesystem | Snapshot, restore, checksum validation, and interrupted write recovery. |
| Offline web assets | ready | Browser with network disabled | UI remains readable with local CSS/icon fallbacks. |

## Next Execution Order

1. Run the automated baseline in an unrestricted local shell and attach command
   output to this log.
2. Run `tests/regression/run_all.py` with loopback networking enabled and confirm
   zero `environment_blocked` rows.
3. Validate Docker on a daemon-enabled host.
4. Validate LLM model discovery/load/inference with the smallest supported GGUF.
5. Move to Raspberry Pi sensors, power, GPS, and removable-storage tests.
