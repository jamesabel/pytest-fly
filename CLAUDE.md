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
tox                                    # full matrix: py312, pypy3, flake8
tox -e py312                           # single tox environment
```

### Code quality
```bash
black src tests                        # format (line length 192)
flake8 src tests                       # lint
mypy src                               # type check
```

### Install for development
```bash
pip install -e .
pip install -r requirements-dev.txt
```

## Architecture

### Entry point
`src/pytest_fly/__main__.py` → `main.py` initializes the Balsa logger and launches the Qt app.

### GUI layer (`src/pytest_fly/gui/`)
- `gui_main.py` — `FlyAppMainWindow`: 5-tab Qt window with a periodic timer (default 3 s) that pulls updates from the runner and refreshes all tabs.
- Tabs: `run_tab/` (start/pause controls), `table_tab/` (per-test status grid), `graph_tab/` (time-based progress chart), `configuration_tab/` (parallelism & thresholds), `about_tab/`.

### Core runner (`src/pytest_fly/pytest_runner/`)
- `pytest_runner.py` — `PytestRunner` (thread): orchestrates worker threads, schedules tests, handles run modes.
- `pytest_process.py` — `PytestProcess`: spawns one `pytest` subprocess per test module, attaches a `ProcessMonitor`.
- `test_list.py` — `GetTests` process: discovers tests via `pytest --collect-only`.
- `process_monitor.py` — `ProcessMonitor` subprocess: samples CPU/memory of the test process tree.
- `utilization.py` — computes system utilization; drives adaptive parallelism.
- `coverage.py` — merges per-process coverage data.

### Persistence
- `db/db.py` — thin wrapper around **msqlite** (thread-safe SQLite). Stores `PytestProcessInfo` records (status, timing, resource usage) — the foundation for RESUME mode.
- `preferences.py` — persists user settings (window geometry, parallelism count, utilization thresholds, run mode) via the **pref** library.

### Key data structures (`interfaces.py`)
- `PytestProcessInfo` — attrs dataclass for a single test module run (status, duration, CPU, memory, pass/fail counts).
- `ScheduledTest` — an ordered item in the execution queue.
- `PytestRunnerState` — enum: IDLE / RUNNING / PAUSED / DONE.
- `RunMode` — enum: RESTART / RESUME / CHECK.

### Parallelism model
Tests are parallelised **at the module level**. All functions inside a module run serially within their process. A `@pytest.mark.singleton` marker forces exclusive execution (no other modules run concurrently). Dynamic mode adjusts the worker count based on CPU/memory utilization thresholds configured in preferences.

## Tech Stack

| Layer | Library |
|---|---|
| GUI | PySide6 (Qt6) |
| DB | msqlite (SQLite3) |
| Logging | balsa |
| Preferences | pref |
| File watching | watchdog |
| Resource monitoring | psutil |
| Data classes | attrs |
| Formatting | black (len=192), flake8, mypy |
| Build | hatchling |
| CI | GitHub Actions + tox |
