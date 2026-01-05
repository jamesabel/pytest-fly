from pytest_fly.pytest_runner.pytest_runner import PytestRunner
from pytest_fly.interfaces import ScheduledTest, ScheduledTests, PyTestFlyExitCode
from pytest_fly.db import PytestProcessInfoDB
from pytest_fly.guid import generate_uuid

from ..paths import get_temp_dir


def test_pytest_runner_simple(app):

    test_name = "test_pytest_runner_simple"

    data_dir = get_temp_dir(test_name)
    run_guid = generate_uuid()

    scheduled_tests = ScheduledTests()
    scheduled_tests.add(ScheduledTest(node_id="tests/test_no_operation.py", singleton=False, duration=None, coverage=None))

    runner = PytestRunner(run_guid, scheduled_tests, 2, data_dir, 3.0)
    runner.start()
    runner.join(10.0)
    with PytestProcessInfoDB(data_dir) as db:
        results = db.query(run_guid)
    assert len(results) == 3
    assert results[0].exit_code == PyTestFlyExitCode.NONE
    assert results[1].exit_code == PyTestFlyExitCode.NONE
    assert results[2].exit_code == PyTestFlyExitCode.OK
