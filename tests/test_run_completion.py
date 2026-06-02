"""Part D — terminal-state run completion and force-stop & reset.

Exercises get_run_completion's terminal/non-terminal classification, the 'finished — N stuck'
case, and that force_stop_and_reset drives every test to a terminal state.
"""

import time

from pytest_fly.db import PytestProcessInfoDB
from pytest_fly.guid import generate_uuid
from pytest_fly.interfaces import PyTestFlyExitCode, PytestProcessInfo
from pytest_fly.pytest_runner import PytestRunner

from .paths import get_temp_dir


def _runner(data_dir, run_guid) -> PytestRunner:
    # Constructed but never started — we only exercise the DB-derived completion methods.
    return PytestRunner(run_guid, [], 1, data_dir, 1.0)


def _write(db, run_guid, name, pid, exit_code, ts):
    db.write(PytestProcessInfo(run_guid, name, pid, exit_code, None, time_stamp=ts))


def test_get_run_completion_classifies_terminal_and_non_terminal():
    data_dir = get_temp_dir("test_get_run_completion_classifies")
    with PytestProcessInfoDB(data_dir) as db:
        db.delete()
    run_guid = generate_uuid()
    now = time.time()
    with PytestProcessInfoDB(data_dir) as db:
        _write(db, run_guid, "t_pass.py", 10, PyTestFlyExitCode.OK, now)
        _write(db, run_guid, "t_fail.py", 11, PyTestFlyExitCode.TESTS_FAILED, now)
        _write(db, run_guid, "t_term.py", 12, PyTestFlyExitCode.TERMINATED, now)
        _write(db, run_guid, "t_stop.py", None, PyTestFlyExitCode.STOPPED, now)
        # QUEUED (pid None, NONE) and RUNNING (pid set, NONE) are non-terminal.
        _write(db, run_guid, "t_queued.py", None, PyTestFlyExitCode.NONE, now)
        _write(db, run_guid, "t_running.py", 13, PyTestFlyExitCode.NONE, now)

    runner = _runner(data_dir, run_guid)
    n_terminal, n_total, stuck = runner.get_run_completion()
    assert n_total == 6
    assert n_terminal == 4
    assert stuck == ["t_queued.py", "t_running.py"]
    assert runner.is_user_complete() is False


def test_get_run_completion_uses_latest_record_per_name():
    data_dir = get_temp_dir("test_get_run_completion_latest")
    with PytestProcessInfoDB(data_dir) as db:
        db.delete()
    run_guid = generate_uuid()
    now = time.time()
    with PytestProcessInfoDB(data_dir) as db:
        # The same test: QUEUED -> RUNNING -> PASS. Latest wins -> terminal.
        _write(db, run_guid, "t.py", None, PyTestFlyExitCode.NONE, now)
        _write(db, run_guid, "t.py", 10, PyTestFlyExitCode.NONE, now + 1)
        _write(db, run_guid, "t.py", 10, PyTestFlyExitCode.OK, now + 2)

    runner = _runner(data_dir, run_guid)
    n_terminal, n_total, stuck = runner.get_run_completion()
    assert (n_terminal, n_total, stuck) == (1, 1, [])
    assert runner.is_user_complete() is True


def test_all_terminal_is_user_complete():
    data_dir = get_temp_dir("test_all_terminal_complete")
    with PytestProcessInfoDB(data_dir) as db:
        db.delete()
    run_guid = generate_uuid()
    now = time.time()
    with PytestProcessInfoDB(data_dir) as db:
        _write(db, run_guid, "a.py", 1, PyTestFlyExitCode.OK, now)
        _write(db, run_guid, "b.py", 2, PyTestFlyExitCode.OK, now)
    runner = _runner(data_dir, run_guid)
    assert runner.is_user_complete() is True


def test_force_stop_and_reset_marks_remaining_stopped():
    data_dir = get_temp_dir("test_force_stop_and_reset")
    with PytestProcessInfoDB(data_dir) as db:
        db.delete()
    run_guid = generate_uuid()
    now = time.time()
    with PytestProcessInfoDB(data_dir) as db:
        _write(db, run_guid, "done.py", 1, PyTestFlyExitCode.OK, now)
        _write(db, run_guid, "wedged.py", 2, PyTestFlyExitCode.NONE, now)  # RUNNING (would be wedged)
        _write(db, run_guid, "blocked_singleton.py", None, PyTestFlyExitCode.NONE, now)  # QUEUED

    runner = _runner(data_dir, run_guid)
    assert runner.is_user_complete() is False  # two non-terminal

    runner.force_stop_and_reset()

    assert runner.was_force_stopped() is True
    assert runner.is_user_complete() is True  # force-stop latch
    n_terminal, n_total, stuck = runner.get_run_completion()
    assert (n_terminal, n_total, stuck) == (3, 3, [])  # everything terminal now
