"""Runner robustness under failure: spawn errors, unclean child exits, resize-after-stop.

Covers the slice-B hardening:
- a worker whose ``PytestProcess.start()`` raises (resource exhaustion) records TERMINATED
  and backs off instead of silently losing the test and churning replacement workers,
- a test child that dies without writing its result record (native crash, ``os._exit``)
  gets a backstop TERMINATED record from its worker,
- ``set_number_of_processes`` never spawns fresh workers into a run that is stopping,
- a worker's ``process`` reference is cleared between tests so stale-name force-stops and
  stale-PID tree-kills are impossible,
- ``ProcessMonitor`` is a daemon child so it can never block its parent's exit.
"""

import os
from queue import Queue
from threading import Event

from pytest_fly.db import PytestProcessInfoDB
from pytest_fly.guid import generate_uuid
from pytest_fly.interfaces import ScheduledTest
from pytest_fly.pytest_runner import PytestRunner
from pytest_fly.pytest_runner import pytest_runner as pytest_runner_module
from pytest_fly.pytest_runner.process_monitor import ProcessMonitor
from pytest_fly.pytest_runner.pytest_process import PytestProcess
from pytest_fly.pytest_runner.pytest_runner import _TestRunner
from pytest_fly.pytest_runner.run_state import latest_states
from pytest_fly.pytest_runner.singleton_coordinator import SingletonCoordinator

from ..paths import get_temp_dir


class _FailsToStart(PytestProcess):
    """Stand-in whose ``start()`` fails the way CreateProcess does at commit exhaustion."""

    def start(self) -> None:
        raise OSError(1455, "The paging file is too small for this operation to complete")


class _DiesUncleanly(PytestProcess):
    """Test child that exits without writing its final result record (as a native crash would)."""

    def run(self) -> None:
        os._exit(3)


def _scheduled(*node_ids: str) -> list[ScheduledTest]:
    return [ScheduledTest(node_id=node_id, singleton=False, duration=None, coverage=None) for node_id in node_ids]


def test_spawn_failure_records_terminated_and_completes(app, monkeypatch):
    """A process-start failure must not lose the test or wedge the run."""
    data_dir = get_temp_dir("test_spawn_failure_records_terminated")
    run_guid = generate_uuid()
    monkeypatch.setattr(pytest_runner_module, "PytestProcess", _FailsToStart)

    runner = PytestRunner(run_guid, _scheduled("tests/test_no_operation.py"), 1, data_dir, update_rate=0.1)
    runner.start()
    assert runner.join(30.0)

    with PytestProcessInfoDB(data_dir) as db:
        states = latest_states(db.query(run_guid))
    assert [info_state.name for info_state in states.values()] == ["TERMINATED"]
    assert runner.is_user_complete()


def test_unclean_child_exit_gets_backstop_terminated_record(app, monkeypatch):
    """A child that dies before its final DB write must not stay "Running" forever."""
    data_dir = get_temp_dir("test_unclean_child_exit_backstop")
    run_guid = generate_uuid()
    monkeypatch.setattr(pytest_runner_module, "PytestProcess", _DiesUncleanly)

    runner = PytestRunner(run_guid, _scheduled("tests/test_no_operation.py"), 1, data_dir, update_rate=0.1)
    runner.start()
    assert runner.join(30.0)

    with PytestProcessInfoDB(data_dir) as db:
        infos = db.query(run_guid)
    states = latest_states(infos)
    assert [info_state.name for info_state in states.values()] == ["TERMINATED"]
    assert runner.is_user_complete()


def test_resize_after_stop_spawns_no_workers(app):
    """set_number_of_processes on a stopping/stopped runner must never start a second pool."""
    data_dir = get_temp_dir("test_resize_after_stop")
    run_guid = generate_uuid()

    runner = PytestRunner(run_guid, _scheduled("tests/test_no_operation.py", "tests/test_3_sec_operation.py"), 1, data_dir, update_rate=0.5)
    runner.start()
    runner.stop()
    runner.join(30.0)
    assert not runner.is_running()

    runner.set_number_of_processes(4)  # previously spawned 4 fresh workers into the stopped run

    assert not runner.is_running()
    with runner._pool_lock:
        alive = [worker for worker in runner._test_runners.values() if worker.is_alive()]
    assert alive == []


def test_worker_clears_process_reference_between_tests(app):
    """After a test finishes, the worker's process reference is None — no stale-name matching."""
    data_dir = get_temp_dir("test_worker_clears_process")
    run_guid = generate_uuid()

    test_queue = Queue()
    for scheduled_test in _scheduled("tests/test_no_operation.py"):
        test_queue.put(scheduled_test)

    worker = _TestRunner(run_guid, test_queue, data_dir, 0.5, SingletonCoordinator(), soft_stop_event=Event())
    worker.start()
    worker.join(30.0)
    assert not worker.is_alive()
    assert worker.process is None


def test_process_monitor_is_daemon():
    """A daemon monitor can never block its parent test process's exit."""
    assert ProcessMonitor("run-guid", "tests/test_x.py", 1234, 1.0).daemon is True
