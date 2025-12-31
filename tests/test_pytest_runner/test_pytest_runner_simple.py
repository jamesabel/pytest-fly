from pathlib import Path

from pytest_fly.pytest_runner.pytest_runner import PytestRunner
from pytest_fly.interfaces import ScheduledTest, ScheduledTests
from pytest_fly.db import PytestProcessInfoDB

from ..paths import get_temp_dir


def test_pytest_runner_simple(app):

    test_name = "test_pytest_runner_simple"

    data_dir = get_temp_dir(test_name)

    scheduled_tests = ScheduledTests()
    scheduled_tests.add(ScheduledTest(node_id="tests/test_no_operation.py", singleton=False, duration=None, coverage=None))

    runner = PytestRunner(scheduled_tests, number_of_processes=2, data_dir=data_dir, update_rate=3.0)
    runner.start()
    runner.join(10.0)
    with PytestProcessInfoDB(data_dir) as db:
        results = db.query()
    assert len(results) == 2
