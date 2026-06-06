# pytest-fly

[![CI](https://github.com/jamesabel/pytest-fly/actions/workflows/main.yml/badge.svg)](https://github.com/jamesabel/pytest-fly/actions/workflows/main.yml)
[![codecov](https://codecov.io/gh/jamesabel/pytest-fly/branch/master/graph/badge.svg)](https://codecov.io/gh/jamesabel/pytest-fly)
[![PyPI](https://img.shields.io/pypi/v/pytest-fly)](https://pypi.org/project/pytest-fly/)
[![Python](https://img.shields.io/pypi/pyversions/pytest-fly)](https://pypi.org/project/pytest-fly/)
[![License](https://img.shields.io/pypi/l/pytest-fly)](https://github.com/jamesabel/pytest-fly/blob/master/LICENSE)


# `pytest-fly`: PyTest for System Tests

Aids the development, debug, and execution of complex code bases and test suites.

## Installation

Install `pytest-fly` via `pip` from `PyPI`:

```
pip install pytest-fly
```

## Features

- Real-time monitoring of test execution in a GUI with six tabs:
  - **Run** — start/stop controls, parallelism and run-mode selectors (Restart or Resume; Resume
    behaves as Check unless the Configuration tab's *Resume Without Program Check* is set), and
    several panels: a Status panel (completion percentage, pass rate, per-state counts, elapsed
    time, average parallelism, coverage, and estimated time remaining), a System Performance
    panel (live CPU, memory, commit-charge, disk I/O, and network I/O charts, with memory and
    commit charge shown as used/total GB alongside percent; the commit-charge warning latches when
    the charge crosses the configured threshold — showing both the absolute GB and percent — and
    stays until dismissed with its **Clear** button), a
    Failed Tests panel with clipboard copy, a Live Output panel streaming pytest output from the
    running tests with elapsed time, last successful run duration, and a progress bar tracking
    progress against the last successful run, and program-under-test version/dirty-git indicators
  - **Graph** — time-based progress chart showing each test module as a horizontal bar
  - **Table** — per-test status grid with elapsed time, peak CPU, memory usage, and individual coverage
  - **Coverage** — line chart of combined code coverage over time with covered/total line counts
  - **Configuration** — Resume-vs-Check toggle, a reorderable test-ordering aspect list, process
    count, refresh rate, utilization thresholds, tooltip line limit, system-metrics chart window,
    Progress Graph font size, target project path (applies on the next run),
    test-results DB directory, and an Expert group (verbose logging, UI performance logging)
  - **About** — system and project information
- Parallel test execution at the module level with configurable process count.
- Three run modes — **Restart** (rerun all tests), **Resume** (skip already-passed tests and
  only re-run failed or unrun tests), and **Check** (resume if the program under test has not
  changed, otherwise restart).
- Graceful interruption — stop the test suite and resume where it left off.
- Per-process resource monitoring — tracks peak CPU and memory usage for each test module.
- Estimated time remaining based on prior run durations, accounting for parallelism.
- Code coverage tracking — each test writes its own coverage data, combined automatically as tests
complete. The Coverage tab plots coverage over time, and the Table shows per-test coverage.
Coverage persists across restarts so previously-passed tests contribute to the total.
- Singleton test support via `@pytest.mark.singleton` — singleton tests run exclusively with no other tests
executing concurrently.
- Workspace-local storage — pytest-fly keeps everything it produces (preferences, logs, and the
test-results DB) under `<workspace>/.pytest-fly/`, where the *workspace* is the directory
pytest-fly is launched from. Nothing is written to per-user "appdir" space, so settings, logs, and
results follow the project rather than the user.
- Configurable program under test (PUT) — the project whose tests are collected and run is set
with `--target <path>` at startup or from the Configuration tab's *Target Project Path* field, and
takes effect on the next run (no relaunch). See [Choosing Which Tests Run](#choosing-which-tests-run).

# Screenshots

### Basic Demo

![pytest-fly demo](https://raw.githubusercontent.com/jamesabel/pytest-fly/master/docs/images/run_animation.gif)

### Run

![Run tab](https://raw.githubusercontent.com/jamesabel/pytest-fly/master/docs/images/run.png)

### Graph

![Graph tab](https://raw.githubusercontent.com/jamesabel/pytest-fly/master/docs/images/graph.png)

### Table

![Table tab](https://raw.githubusercontent.com/jamesabel/pytest-fly/master/docs/images/table.png)

### Coverage

![Coverage tab](https://raw.githubusercontent.com/jamesabel/pytest-fly/master/docs/images/coverage.png)

### Configuration

![Configuration tab](https://raw.githubusercontent.com/jamesabel/pytest-fly/master/docs/images/configuration.png)

### About

![About tab](https://raw.githubusercontent.com/jamesabel/pytest-fly/master/docs/images/about.png)

> Screenshots and the demo GIF above are produced by `python scripts/capture_assets.py`,
> which drives the GUI against the auto-generated demo suite in `demo/demo.py`.

## Parallelism

By default, `pytest-fly` executes *modules* (.py files) in parallel. 

Functions *inside* a module are executed serially with respect to each other. No parallelism is performed for 
functions inside a module. For example, if a set of tests use a shared resource that does not support concurrent 
access, putting those tests in the same module ensures the tests do not conflict.

Modules can optionally be marked as a singleton via the `@pytest.mark.singleton` marker. When a singleton test 
runs, all other workers wait until it completes before starting new tests. This is enforced at runtime, not 
just by scheduling order.

In `pytest` terms, each module is run in a separate subprocess. Therefore, a pytest fixture with a `session` scope 
will actually be executed multiple times, once for each module.

Note that test concurrency in `pytest-fly` is different from `pytest-xdist`. `group-by` in `pytest-xdist` is
analogous to putting the tests in the same module in `pytest-fly`.

## Test Scheduling

`pytest-fly` orders tests to surface actionable information earlier. The Configuration tab's
**Test Ordering** widget is a reorderable, per-row-checkable list of aspects — each can be
individually enabled/disabled, and its position in the list sets priority (topmost enabled row
is the primary sort; rows below it break ties). The available aspects are:

- **Failed tests** — tests that failed in the prior run run first, so developers get faster
  feedback on tests they are likely fixing.
- **Never-run tests** — tests with no record in the database (across any program-under-test
  version) run first, giving developers adding new tests immediate feedback.
- **Longest prior execution time** — slowest passing tests run first, helping parallel runs by
  starting the critical path earliest so shorter tests backfill the remaining workers.
- **Coverage efficiency (lines/sec)** — tests with the highest lines-covered-per-second run
  first, so if there is a problem in the code it is more likely to be found earlier in the run.

All aspects apply in every run mode, including Restart — prior-run data shapes execution *order*,
not *which* tests run. Tests missing the data an aspect needs tie for last under that aspect.
`singleton` tests always run last, regardless of these settings, to maximize parallel throughput
before exclusive execution begins.

## Choosing Which Tests Run

`pytest-fly` discovers tests by running `pytest --collect-only` against the **Target Project Path**
(the program under test) and collecting *every* test under that path, recursively. So the simplest
way to control which tests run is to point the Target Project Path at the directory you want — for
example, set it to `<project>/tests` to run only the tests there and skip sibling directories such
as example or demo code.

Set it with `--target <path>` at startup, or in the Configuration tab's **Target Project Path**
field (Browse… to pick a directory). Changes apply on the next run. Your project-root `pytest.ini`
/ `pyproject.toml` is still located normally, so `pythonpath`, markers, and other settings keep
working — only the *collection scope* narrows to the chosen path.

> **Note:** pytest's `testpaths` setting is **not** honored under pytest-fly. pytest-fly passes the
> Target Project Path to pytest as an explicit positional argument, and an explicit path overrides
> `testpaths` (which pytest only consults when invoked with no path arguments). To scope collection,
> use the Target Project Path, or — if you need the Target Project Path to stay at the project root
> (e.g. for whole-project coverage) — exclude directories with a root `conftest.py`:
>
> ```python
> # conftest.py (project root)
> collect_ignore_glob = ["fly_demo/*"]
> ```

# What's Up With The Name?

Originally this was going to be a "watcher", so it's like a "fly on the wall".  As it turns out, it became a runner
to provide the desired control and observability. "Fly" can mean:

- Observes code execution ("fly on the wall")
- Fast (offers parallelism so your tests "fly" by quickly)
- Cool ("pretty fly")