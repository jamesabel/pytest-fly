# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

**pytest-fly** is a PySide6 GUI application that enhances pytest with:
- Parallel test execution at the module level (each `.py` file runs in a separate pytest process)
- Resumable runs (RESTART / RESUME / CHECK modes — skip already-passed tests)
- Real-time monitoring of CPU/memory per test process
- Dynamic parallelism that adapts to system utilization
- Code-change detection that auto-restarts the suite

## Commands

### Run the app
```bash
python -m pytest_fly
```

### Run tests
```bash
pytest tests/                          # full suite
pytest tests/test_foo.py               # single file
pytest tests/test_foo.py::test_bar     # single test
tox                                    # full matrix: py312, pypy3, ruff
tox -e py312                           # single tox environment
```

### Code quality
```bash
ruff check src tests                   # lint
ruff format src tests                  # format (line length 192)
ty check src                           # type check
```

### Install for development
```bash
pip install -e .
pip install -r requirements-dev.txt
```

## Architecture

### Entry point
`src/pytest_fly/__main__.py` → `main.py` initializes the stdlib-based logger (`logger.py`) and launches the Qt app.

### GUI layer (`src/pytest_fly/gui/`)
- `gui_main.py` — `FlyAppMainWindow`: 7-tab Qt window with a periodic timer (default 3 s) that pulls updates from the runner and refreshes all tabs.
- Tabs: `run_tab/` (run/stop controls, status, system metrics, failed tests, live output), `graph_tab/` (time-based progress chart), `table_tab/` (per-test status grid), `coverage_tab/` (coverage-over-time chart), `log_tab/` (live application event log — admission-gate, resource-guard, and stall-watchdog events, each line date/time-prefixed; default view shows tagged `EVENT_EXTRA` events + warnings, Verbose shows all INFO+), `configuration_tab/` (parallelism, thresholds, gates), `about_tab/`.

### Core runner (`src/pytest_fly/pytest_runner/`)
- `pytest_runner.py` — `PytestRunner` (thread): orchestrates worker threads, schedules tests, handles run modes.
- `stall_watchdog.py` — `StallWatchdog`: read-only wedged-run detection with opt-in auto force-stop.
- `admission.py` — `AdmissionGate` + `AdmissionGateConfig`: dispatch throttles (process-count / commit-charge / CPU).
- `run_state.py` — classifies DB records into display states (`PytestRunState`, `state_of`, `latest_states`).
- `singleton_coordinator.py` — `SingletonCoordinator`: serializes `@pytest.mark.singleton` tests against all workers.
- `monitor_thread.py` — `MonitorThread`: shared daemon-loop base for the stall watchdog and resource guard.
- `resource_guard.py` — `ResourceGuard`: opt-in low-resource (disk / commit space) automatic soft stop.
- `pytest_process.py` — `PytestProcess`: spawns one `pytest` subprocess per test module, attaches a `ProcessMonitor`.
- `test_list.py` — `GetTests` process: discovers tests via `pytest --collect-only`.
- `process_monitor.py` — `ProcessMonitor` subprocess: samples CPU/memory of the test process tree; `SubtreeCpuSampler` (shared persistent-handle CPU sampling).
- `system_monitor.py` — `SystemMonitor` subprocess: system-wide CPU/memory/commit/disk/network sampling for the Run tab charts.
- `commit_memory.py` — Windows commit-charge readers and psutil subtree helpers.
- `coverage.py` — merges per-process coverage data.
- `ordering.py` — applies the user's test-ordering aspects; `live_output.py` — per-test live-output file paths.

### Persistence
- `db/db.py` — stores `PytestProcessInfo` records (status, timing, resource usage) — the foundation for RESUME mode. Two access classes: `PytestProcessInfoDB` (read/write via **msqlite**, whose context manager holds the DB's EXCLUSIVE lock) and `PytestProcessInfoReader` (read-only, lock-free WAL snapshot reads — required for the GUI thread and monitor threads so they never contend with test-process writers).
- `preferences.py` — persists user settings (window geometry, parallelism count, utilization thresholds, run mode) via the **pref** library.

### Key data structures (`interfaces.py`)
- `PytestProcessInfo` — frozen stdlib dataclass for a single test module run (status, timing, CPU, memory, commit).
- `ScheduledTest` — an ordered item in the execution queue.
- `PytestRunnerState` — enum: QUEUED / RUNNING / PASS / FAIL / TERMINATED / STOPPED.
- `RunMode` — enum: RESTART / RESUME / CHECK.

### Parallelism model
Tests are parallelised **at the module level**. All functions inside a module run serially within their process. A `@pytest.mark.singleton` marker forces exclusive execution (no other modules run concurrently). Dynamic mode adjusts the worker count based on CPU/memory utilization thresholds configured in preferences.

## Tech Stack

| Layer | Library |
|---|---|
| GUI | PySide6 (Qt6) |
| DB | msqlite (SQLite3) |
| Logging | stdlib logging |
| Preferences | pref |
| File watching | watchdog |
| Resource monitoring | psutil |
| Data classes | stdlib dataclasses (attrs for preferences) |
| Linting/Formatting | ruff (len=192) |
| Type checking | ty |
| Build | hatchling |
| CI | GitHub Actions + tox |
