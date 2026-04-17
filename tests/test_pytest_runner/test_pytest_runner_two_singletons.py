from pytest_fly.db import PytestProcessInfoDB
from pytest_fly.guid import generate_uuid
from pytest_fly.interfaces import PyTestFlyExitCode, ScheduledTest
from pytest_fly.pytest_runner import PytestRunner

from ..paths import get_temp_dir


def test_pytest_runner_two_singletons(app):
    """Two singleton tests must serialize — their running intervals must not overlap."""

    test_name = "test_pytest_runner_two_singletons"

    scheduled_tests = sorted(
        [
            ScheduledTest(node_id="tests/test_singleton_a.py", singleton=True, duration=None, coverage=None),
            ScheduledTest(node_id="tests/test_singleton_b.py", singleton=True, duration=None, coverage=None),
        ]
    )

    run_guid = generate_uuid()
    data_dir = get_temp_dir(test_name)

    runner = PytestRunner(run_guid, scheduled_tests, number_of_processes=2, data_dir=data_dir, update_rate=0.5)
    runner.start()
    runner.join(120.0)
    assert not runner.is_running()

    with PytestProcessInfoDB(data_dir) as db:
        query_results = db.query(run_guid)

    by_test: dict[str, list] = {}
    for r in query_results:
        by_test.setdefault(r.name, []).append(r)

    assert set(by_test.keys()) == {"tests/test_singleton_a.py", "tests/test_singleton_b.py"}

    intervals = []
    for name, records in by_test.items():
        running = [r for r in records if r.pid is not None and r.exit_code == PyTestFlyExitCode.NONE]
        completed = [r for r in records if r.exit_code == PyTestFlyExitCode.OK]
        assert len(running) == 1, f"{name}: expected one 'running' record, got {len(running)}"
        assert len(completed) == 1, f"{name}: expected one 'completed' record, got {len(completed)}"
        intervals.append((running[0].time_stamp, completed[0].time_stamp, name))

    intervals.sort()
    (start_a, end_a, name_a), (start_b, end_b, name_b) = intervals
    assert end_a <= start_b, f"Singleton intervals overlapped: {name_a}[{start_a}..{end_a}] vs {name_b}[{start_b}..{end_b}]"
