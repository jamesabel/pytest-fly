from pytest_fly.db import PytestProcessInfoDB
from pytest_fly.guid import generate_uuid
from pytest_fly.interfaces import PyTestFlyExitCode, ScheduledTest
from pytest_fly.pytest_runner import PytestRunner
from pytest_fly.pytest_runner.resource_guard import ResourceGuardConfig

from ..paths import get_temp_dir


def test_pytest_runner_resource_guard_soft_stops(app):
    """A breaching resource guard soft-stops the run: the running test finishes, queued tests are STOPPED.

    An impossibly high free-disk minimum makes the guard breach on every sample, so it
    triggers (after its consecutive-sample debounce) while the first test is still running.
    """

    test_name = "test_pytest_runner_resource_guard_soft_stops"

    data_dir = get_temp_dir(test_name)
    run_guid = generate_uuid()

    # A 3-second test first, then an instant test. With 1 worker the second test stays
    # queued while the first runs, giving the guard time to trigger the soft stop.
    scheduled_tests = [
        ScheduledTest(node_id="tests/test_3_sec_operation.py", singleton=False, duration=None, coverage=None),
        ScheduledTest(node_id="tests/test_no_operation.py", singleton=False, duration=None, coverage=None),
    ]

    resource_guard_config = ResourceGuardConfig(enabled=True, min_free_disk_gb=1e9)  # no drive has 1e9 GB free — always breaching
    runner = PytestRunner(run_guid, scheduled_tests, number_of_processes=1, data_dir=data_dir, update_rate=1.0, resource_guard_config=resource_guard_config)
    runner.start()
    runner.join(60.0)

    assert not runner.is_running()
    assert runner.is_soft_stop_pending()
    info = runner.get_resource_guard_info()
    assert info is not None
    assert info.triggered is True
    assert "disk" in info.reason

    with PytestProcessInfoDB(data_dir) as db:
        results = db.query(run_guid)

    # The first test completed normally (a soft stop never kills a running test).
    first_test_results = [r for r in results if r.name == "tests/test_3_sec_operation.py"]
    assert first_test_results[-1].exit_code == PyTestFlyExitCode.OK

    # The queued second test was marked STOPPED by the guard-requested soft stop.
    second_test_results = [r for r in results if r.name == "tests/test_no_operation.py"]
    assert second_test_results[-1].exit_code == PyTestFlyExitCode.STOPPED


def test_pytest_runner_resource_guard_healthy_run_completes(app):
    """With generous thresholds the guard stays quiet and every test runs to completion."""

    test_name = "test_pytest_runner_resource_guard_healthy_run_completes"

    data_dir = get_temp_dir(test_name)
    run_guid = generate_uuid()

    scheduled_tests = [ScheduledTest(node_id="tests/test_no_operation.py", singleton=False, duration=None, coverage=None)]

    resource_guard_config = ResourceGuardConfig(enabled=True, min_free_disk_gb=0.0, commit_threshold=1.0)  # never breaches
    runner = PytestRunner(run_guid, scheduled_tests, number_of_processes=1, data_dir=data_dir, update_rate=1.0, resource_guard_config=resource_guard_config)
    runner.start()
    runner.join(60.0)

    assert not runner.is_running()
    assert not runner.is_soft_stop_pending()
    info = runner.get_resource_guard_info()
    assert info is not None
    assert info.triggered is False

    with PytestProcessInfoDB(data_dir) as db:
        results = db.query(run_guid)
    test_results = [r for r in results if r.name == "tests/test_no_operation.py"]
    assert test_results[-1].exit_code == PyTestFlyExitCode.OK


def test_pytest_runner_resource_guard_disabled_reports_none(app):
    """With the guard disabled (the default), no guard info is published."""

    test_name = "test_pytest_runner_resource_guard_disabled_reports_none"

    data_dir = get_temp_dir(test_name)
    run_guid = generate_uuid()

    scheduled_tests = [ScheduledTest(node_id="tests/test_no_operation.py", singleton=False, duration=None, coverage=None)]

    runner = PytestRunner(run_guid, scheduled_tests, number_of_processes=1, data_dir=data_dir, update_rate=1.0)
    runner.start()
    runner.join(60.0)

    assert runner.get_resource_guard_info() is None
