# pytest-fly

`pytest-fly` aides the development, debug, and execution of complex code bases and test suites.

## Features of `pytest-fly`

- Real-time monitor test execution in a GUI. Displays what tests are currently running, what tests have completed,
and what tests have failed. A time-based graph provides a visual representation of test progress.
- Resumable test execution. Only runs tests that have not yet been run or have failed.
- Graceful interruption of test execution. Allows the user to stop the test suite and then resume where it left off.
- Checks the code under test and restarts the test run from scratch if the code has changed.
- Optimally run tests in parallel. Monitors system resources and dynamically adjusts the number of 
parallel tests accordingly.
- Provides an estimate of the time remaining for the test suite to complete. Uses prior test run times to estimate 
the time remaining.
- Optional code coverage. Code coverage can also run tests in parallel.
- Run specific tests as a singleton via pytest markers (pytest.marker.singleton).

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

Functions can optionally be run as a singleton via the `pytest.mark.singleton` marker. No other tests are run 
at the same time `singleton` functions are run.

In `pytest` terms, each module will be run as a separate `session`. Therefore, a pytest fixture with a `session` scope 
will actually be executed multiple times, once for each modulee.

Note that test concurrency in `pytest-fly` is different from `pytest-xdist`. `group-by` in `pytest-xdist` is
analogous to putting the tests in the same module in `pytest-fly`.

## Test Scheduling

`pytest-fly` attempts to order tests to make the best use of the test developer's time. The goal is for the more 
actionable and insightful information to appear earlier. In general, `pytest-fly` takes the following into account 
when scheduling tests:

1. Failed tests are re-run first. This is beneficial when a test developer is fixing failed tests. Note that if a 
test is *expected* to fail, it should be temporarily marked as such to avoid spending time re-running a test that 
will merely fail.
2. Tests with a higher coverage over time (i.e., lines/second) are run earlier. This way, if there is a problem in the 
code, it is more likely to be found earlier in the test run.
3. Tests are scheduled for maximum parallelism. Long-running tests are started earlier to minimize overall runtime. 
Also, tests that consume large amounts of particular resources (e.g., memory, file system, etc.) tend to be paired 
with other tests that do not use as much of those resources.
4. `singleton` tests are run last. This is to attempt to get higher coverage earlier in the test run.
