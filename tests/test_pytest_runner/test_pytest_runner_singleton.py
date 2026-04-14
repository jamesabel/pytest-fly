from pytest_fly.pytest_runner import PytestRunner
from pytest_fly.guid import generate_uuid
from pytest_fly.interfaces import ScheduledTest, PyTestFlyExitCode
from pytest_fly.db import PytestProcessInfoDB

from ..paths import get_temp_dir


def test_pytest_runner_singleton(app):
    """Verify that a singleton test runs exclusively — not overlapping with other tests."""

    test_name = "test_pytest_runner_singleton"

    # Two normal tests (run in parallel) plus one singleton (must run alone).
    # The singleton is last because ScheduledTest sorting puts singletons at the end.
    scheduled_tests = sorted(
        [
            ScheduledTest(node_id="tests/test_no_operation.py", singleton=False, duration=None, coverage=None),
            ScheduledTest(node_id="tests/test_3_sec_operation.py", singleton=False, duration=None, coverage=None),
            ScheduledTest(node_id="tests/test_singleton.py", singleton=True, duration=None, coverage=None),
        ]
    )

    run_guid = generate_uuid()
    data_dir = get_temp_dir(test_name)

    runner = PytestRunner(run_guid, scheduled_tests, number_of_processes=2, data_dir=data_dir, update_rate=1.0)
    runner.start()
    runner.join(120.0)
    assert not runner.is_running()

    with PytestProcessInfoDB(data_dir) as db:
        query_results = db.query(run_guid)

    # Each test produces 3 DB records: queued (no pid), running (has pid), completed (has exit code).
    # 3 tests * 3 records = 9 total.
    assert len(query_results) == 9

    # Group results by test name
    test_results = {}
    for r in query_results:
        test_results.setdefault(r.name, []).append(r)

    assert len(test_results) == 3

    # The singleton test must have started (its "running" record timestamp)
    # AFTER all normal tests finished (their final record timestamp).
    singleton_records = test_results["tests/test_singleton.py"]
    singleton_running = [r for r in singleton_records if r.pid is not None and r.exit_code == PyTestFlyExitCode.NONE]
    assert len(singleton_running) == 1
    singleton_start_time = singleton_running[0].time_stamp

    for test_name_key, records in test_results.items():
        if test_name_key == "tests/test_singleton.py":
            continue
        # The final record for each normal test is the completion record
        final_record = records[-1]
        assert final_record.exit_code == PyTestFlyExitCode.OK, f"{test_name_key} did not pass: {final_record.exit_code}"
        assert final_record.time_stamp <= singleton_start_time, (
            f"Singleton test started at {singleton_start_time} but "
            f"{test_name_key} finished at {final_record.time_stamp} — singleton was not exclusive"
        )
