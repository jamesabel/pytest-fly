# pytest-fly

[![CI](https://github.com/jamesabel/pytest-fly/actions/workflows/main.yml/badge.svg)](https://github.com/jamesabel/pytest-fly/actions/workflows/main.yml)
[![codecov](https://codecov.io/gh/jamesabel/pytest-fly/branch/master/graph/badge.svg)](https://codecov.io/gh/jamesabel/pytest-fly)
[![PyPI](https://img.shields.io/pypi/v/pytest-fly)](https://pypi.org/project/pytest-fly/)
[![Python](https://img.shields.io/pypi/pyversions/pytest-fly)](https://pypi.org/project/pytest-fly/)
[![License](https://img.shields.io/pypi/l/pytest-fly)](https://github.com/jamesabel/pytest-fly/blob/master/LICENSE)

`pytest-fly` aids the development, debug, and execution of complex code bases and test suites.

## Features

- Real-time monitoring of test execution in a GUI with six tabs:
  - **Run** — start/stop controls, run mode selection (Restart/Resume/Check), and several panels:
    a Status panel (completion percentage, pass rate, per-state counts, elapsed time, average
    parallelism, coverage, and estimated time remaining), a System Performance panel (live CPU
    and memory charts, with memory shown as used/total GB alongside percent), a Failed Tests panel
    with clipboard copy, and program-under-test version/dirty-git indicators
  - **Graph** — time-based progress chart showing each test module as a horizontal bar
  - **Table** — per-test status grid with elapsed time, peak CPU, memory usage, and individual coverage
  - **Coverage** — line chart of combined code coverage over time with covered/total line counts
  - **Configuration** — parallelism settings, refresh rate, and utilization thresholds
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

## Installation

You can install `pytest-fly` via `pip` from `PyPI`:

```
pip install pytest-fly
```

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

`pytest-fly` orders tests to surface actionable information earlier:

1. When **Prioritize Never-Run Tests** is enabled in the Configuration tab, tests with no record in
the database (across any program-under-test version) are promoted to the front of the queue, giving
developers adding new tests immediate feedback. This takes precedence over failed-first and
coverage-efficiency ordering.
2. Tests that failed in the prior run are re-run first, so developers get faster feedback on tests they are 
likely fixing.
3. When prior run data is available, tests with higher coverage efficiency (lines/second) are run earlier. 
This way, if there is a problem in the code, it is more likely to be found earlier in the test run.
4. `singleton` tests are run last to maximize parallel throughput before exclusive execution begins.
