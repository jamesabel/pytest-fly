from pytest_fly.pytest_runner import PytestRunner
from pytest_fly.guid import generate_uuid
from pytest_fly.interfaces import ScheduledTest
from pytest_fly.db import PytestProcessInfoDB

from ..paths import get_temp_dir


def test_pytest_runner_multiprocess(app):

    test_name = "test_pytest_runner_multiprocess"

    tests = ["tests/test_no_operation.py", "tests/test_3_sec_operation.py"]

    scheduled_tests = []
    for test in tests:
        scheduled_tests.append(ScheduledTest(node_id=test, singleton=False, duration=None, coverage=None))

    run_guid = generate_uuid()
    data_dir = get_temp_dir(test_name)

    runner = PytestRunner(run_guid, scheduled_tests, number_of_processes=2, data_dir=data_dir, update_rate=3.0)
    runner.start()
    runner.join(100.0)
    assert not runner.is_running()

    with PytestProcessInfoDB(data_dir) as db:
        query_results = db.query(run_guid)

    assert len(query_results) == 6

    # get results for each test
    test_results = {}
    for test in tests:
        test_results[test] = [r for r in query_results if r.name == test]

    print(test_results)

    results = test_results[tests[0]]  # no operation test
    duration = results[2].time_stamp - results[1].time_stamp
    print(f"{tests[0]}: {duration=}")
    assert 0.0 < duration < 3.0  # 1.7821760177612305 seen

    results = test_results[tests[1]]  # 3 sec operation
    duration = results[2].time_stamp - results[1].time_stamp
    print(f"{tests[1]}: {duration=}")
    assert 3.0 < duration < 6.0  # 4.801987171173096 seen
