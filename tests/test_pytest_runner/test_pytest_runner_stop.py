import time

from pytest_fly.pytest_runner import PytestRunner, PytestRunState
from pytest_fly.interfaces import ScheduledTest, PyTestFlyExitCode, PytestRunnerState
from pytest_fly.db import PytestProcessInfoDB
from pytest_fly.guid import generate_uuid

from ..paths import get_temp_dir


def test_pytest_runner_stop(app):

    test_name = "test_pytest_runner_stop"

    data_dir = get_temp_dir(test_name)
    run_guid = generate_uuid()

    scheduled_tests = [ScheduledTest(node_id="tests/test_long_operation.py", singleton=False, duration=None, coverage=None)]

    runner = PytestRunner(run_guid, scheduled_tests, number_of_processes=2, data_dir=data_dir, update_rate=3.0)
    runner.start()
    time.sleep(3.0)
    runner.stop()
    runner.join(10.0)
    with PytestProcessInfoDB(data_dir) as db:
        results = db.query()

    pytest_run_state = PytestRunState(results)
    assert pytest_run_state.get_state() == PytestRunnerState.TERMINATED

    assert results[0].exit_code == PyTestFlyExitCode.NONE
    assert results[0].pid is None
    assert results[1].exit_code == PyTestFlyExitCode.NONE
    assert results[1].pid is not None
    assert results[2].exit_code == PyTestFlyExitCode.TERMINATED
    assert results[2].pid is None
