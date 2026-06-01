import time

from pytest_fly.db import PytestProcessInfoDB
from pytest_fly.guid import generate_uuid
from pytest_fly.interfaces import PyTestFlyExitCode, ScheduledTest
from pytest_fly.pytest_runner import PytestRunner

from ..paths import get_temp_dir


def test_pytest_runner_grow_pool(app):
    """Growing the pool mid-run lets queued tests run in parallel without a restart."""

    data_dir = get_temp_dir("test_pytest_runner_grow_pool")
    with PytestProcessInfoDB(data_dir) as db:
        db.delete()
    run_guid = generate_uuid()

    # Two distinct 3-second modules. With one worker they run serially (~9s incl.
    # process startup); growing to two workers runs them in parallel (~5s).
    scheduled_tests = [
        ScheduledTest(node_id="tests/test_3_sec_operation.py", singleton=False, duration=None, coverage=None),
        ScheduledTest(node_id="tests/test_sleep.py", singleton=False, duration=None, coverage=None),
    ]

    runner = PytestRunner(run_guid, scheduled_tests, number_of_processes=1, data_dir=data_dir, update_rate=1.0)
    start = time.time()
    runner.start()
    time.sleep(0.5)  # let run() spin up the initial single worker
    runner.set_number_of_processes(2)
    completed = runner.join(30.0)
    elapsed = time.time() - start

    assert completed
    assert not runner.is_running()

    with PytestProcessInfoDB(data_dir) as db:
        results = db.query(run_guid)
    for name in ("tests/test_3_sec_operation.py", "tests/test_sleep.py"):
        final = [r for r in results if r.name == name][-1]
        assert final.exit_code == PyTestFlyExitCode.OK

    # Serial execution would take ~9s; parallel ~5s. The midpoint threshold proves
    # the second worker spawned by the resize actually picked up the queued test.
    assert elapsed < 7.5, f"expected parallel execution after grow, took {elapsed:.1f}s"


def test_pytest_runner_shrink_pool_preserves_queue(app):
    """Shrinking the pool retires a worker without losing the queued test — a survivor runs it."""

    data_dir = get_temp_dir("test_pytest_runner_shrink_pool_preserves_queue")
    with PytestProcessInfoDB(data_dir) as db:
        db.delete()
    run_guid = generate_uuid()

    # Two long tests occupy both workers; one instant test stays queued.
    scheduled_tests = [
        ScheduledTest(node_id="tests/test_3_sec_operation.py", singleton=False, duration=None, coverage=None),
        ScheduledTest(node_id="tests/test_sleep.py", singleton=False, duration=None, coverage=None),
        ScheduledTest(node_id="tests/test_no_operation.py", singleton=False, duration=None, coverage=None),
    ]

    runner = PytestRunner(run_guid, scheduled_tests, number_of_processes=2, data_dir=data_dir, update_rate=1.0)
    runner.start()
    time.sleep(1.0)  # let both workers pick up the two long tests
    runner.set_number_of_processes(1)  # retire one worker; the survivor must drain the queue
    completed = runner.join(30.0)

    assert completed
    assert not runner.is_running()

    with PytestProcessInfoDB(data_dir) as db:
        results = db.query(run_guid)

    # The queued instant test must NOT be marked STOPPED — a surviving worker runs it.
    for name in ("tests/test_3_sec_operation.py", "tests/test_sleep.py", "tests/test_no_operation.py"):
        final = [r for r in results if r.name == name][-1]
        assert final.exit_code == PyTestFlyExitCode.OK, f"{name} ended {final.exit_code!r}, expected OK"
