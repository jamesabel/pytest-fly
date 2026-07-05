import time

from pytest_fly.db import PytestProcessInfoDB
from pytest_fly.guid import generate_uuid
from pytest_fly.interfaces import PyTestFlyExitCode, ScheduledTest
from pytest_fly.pytest_runner import PytestRunner

from ..paths import get_temp_dir


def test_pytest_runner_cancel_soft_stop(app):
    """Canceling a soft stop resumes the queued tests and the run completes normally."""

    test_name = "test_pytest_runner_cancel_soft_stop"

    data_dir = get_temp_dir(test_name)
    run_guid = generate_uuid()

    # Schedule a 3-second test first, then an instant test.
    # With 1 worker process, the second test stays queued while the first runs,
    # leaving a window to soft-stop and then cancel before the first test finishes.
    scheduled_tests = [
        ScheduledTest(node_id="tests/test_3_sec_operation.py", singleton=False, duration=None, coverage=None),
        ScheduledTest(node_id="tests/test_no_operation.py", singleton=False, duration=None, coverage=None),
    ]

    runner = PytestRunner(run_guid, scheduled_tests, number_of_processes=1, data_dir=data_dir, update_rate=1.0)
    runner.start()
    time.sleep(1.0)  # wait for the first test to start running
    runner.soft_stop()
    assert runner.cancel_soft_stop() is True  # cancel while the first test is still running
    runner.join(60.0)

    assert not runner.is_running()

    with PytestProcessInfoDB(data_dir) as db:
        results = db.query(run_guid)

    # Both tests should have completed normally — the canceled soft stop must not
    # have marked the queued test STOPPED.
    for name in ("tests/test_3_sec_operation.py", "tests/test_no_operation.py"):
        test_results = [r for r in results if r.name == name]
        assert test_results, f"no records for {name}"
        assert test_results[-1].exit_code == PyTestFlyExitCode.OK, name


def test_pytest_runner_cancel_soft_stop_too_late(app):
    """Once a run has wound down, cancel_soft_stop reports it is too late."""

    test_name = "test_pytest_runner_cancel_soft_stop_too_late"

    data_dir = get_temp_dir(test_name)
    run_guid = generate_uuid()

    scheduled_tests = [ScheduledTest(node_id="tests/test_no_operation.py", singleton=False, duration=None, coverage=None)]

    runner = PytestRunner(run_guid, scheduled_tests, number_of_processes=1, data_dir=data_dir, update_rate=0.5)
    runner.start()
    assert runner.join(60.0)

    assert runner.cancel_soft_stop() is False
