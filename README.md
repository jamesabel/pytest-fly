# pytest-fly

`pytest-fly` aides the development, debug, and execution of complex code bases and test suites.

## Features of `pytest-fly`

- Real-time monitor test execution in a GUI. Displays what tests are currently running, what tests have completed,
and what tests have failed. A time-based graph provides a visual representation of test progress.
- Resumable test execution. Only runs tests that have not yet been run or have failed.
- Graceful interruption of test execution. Allows the user to stop the test suite and then resume where it left off.
- Checks the code under test and restarts test run from scratch if the code has changed.
- Optimally run tests in parallel. Accesses and monitors system resources, and dynamically adjusts the number of 
parallel tests accordingly.
- Provides an estimate of the time remaining for the test suite to complete. Uses prior test run times to estimate 
the time remaining.
- Optional code coverage. Code coverage can also run tests in parallel.
- Run specific tests serially via pytest markers. Useful when specific tests need to run serially.

## Installation

You can install `pytest-fly` via `pip` from `PyPI`:

```
    pip install pytest-fly
```
