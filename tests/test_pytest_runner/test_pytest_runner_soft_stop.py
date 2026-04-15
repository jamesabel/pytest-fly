import time

from pytest_fly.db import PytestProcessInfoDB
from pytest_fly.guid import generate_uuid
from pytest_fly.interfaces import PyTestFlyExitCode, PytestRunnerState, ScheduledTest
from pytest_fly.pytest_runner import PytestRunner, PytestRunState

from ..paths import get_temp_dir


def test_pytest_runner_soft_stop(app):
    """Soft stop lets the running test finish and marks queued tests as STOPPED."""

    test_name = "test_pytest_runner_soft_stop"

    data_dir = get_temp_dir(test_name)
    run_guid = generate_uuid()

    # Schedule a 3-second test first, then an instant test.
    # With 1 worker process, the second test stays queued while the first runs.
    scheduled_tests = [
        ScheduledTest(node_id="tests/test_3_sec_operation.py", singleton=False, duration=None, coverage=None),
        ScheduledTest(node_id="tests/test_no_operation.py", singleton=False, duration=None, coverage=None),
    ]

    runner = PytestRunner(run_guid, scheduled_tests, number_of_processes=1, data_dir=data_dir, update_rate=1.0)
    runner.start()
    time.sleep(2.0)  # wait for the first test to start running
    runner.soft_stop()
    runner.join(30.0)  # the first test should finish naturally (~3 seconds)

    assert not runner.is_running()

    with PytestProcessInfoDB(data_dir) as db:
        results = db.query(run_guid)

    # The first test (test_3_sec_operation) should have completed normally.
    first_test_results = [r for r in results if r.name == "tests/test_3_sec_operation.py"]
    last_first = first_test_results[-1]
    assert last_first.exit_code == PyTestFlyExitCode.OK

    # The second test (test_no_operation) should be marked as STOPPED.
    second_test_results = [r for r in results if r.name == "tests/test_no_operation.py"]
    last_second = second_test_results[-1]
    assert last_second.exit_code == PyTestFlyExitCode.STOPPED

    pytest_run_state = PytestRunState(second_test_results)
    assert pytest_run_state.get_state() == PytestRunnerState.STOPPED
