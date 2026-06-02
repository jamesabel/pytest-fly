"""Part C — process-count + commit-charge admission gates.

Covers subtree_process_count, the gate composition (AND), the min-1 forward-progress
override, abort-while-deferring, and fail-open behavior.
"""

import os
from pathlib import Path
from queue import Queue

from pytest_fly.pytest_runner import pytest_runner
from pytest_fly.pytest_runner.commit_memory import subtree_process_count
from pytest_fly.pytest_runner.pytest_runner import _AdmissionGateConfig, _SingletonCoordinator, _TestRunner


def test_subtree_process_count_current_process():
    assert subtree_process_count(os.getpid()) >= 1


def test_subtree_process_count_invalid_pid_fails_open():
    assert subtree_process_count(-1) == 0


def _make_runner(gate_config: _AdmissionGateConfig, coordinator: _SingletonCoordinator | None = None) -> _TestRunner:
    coordinator = coordinator or _SingletonCoordinator()
    return _TestRunner(
        "run-guid",
        Queue(),
        Path("."),
        0.01,  # tiny update_rate so the defer loop polls quickly
        coordinator,
        controller_pid=os.getpid(),
        gate_config=gate_config,
    )


def test_gate_disabled_admits_immediately():
    runner = _make_runner(_AdmissionGateConfig())  # both gates off
    assert runner._await_admission(lambda: False) is True


def test_process_gate_admits_under_ceiling(monkeypatch):
    monkeypatch.setattr(pytest_runner, "subtree_process_count", lambda pid: 3)
    runner = _make_runner(_AdmissionGateConfig(process_count_gate_enabled=True, max_descendant_processes=10))
    assert runner._await_admission(lambda: False) is True


def test_process_gate_min1_admits_when_nothing_in_flight(monkeypatch):
    # Over ceiling, but the coordinator reports nothing running -> min-1 forces progress.
    monkeypatch.setattr(pytest_runner, "subtree_process_count", lambda pid: 999)
    coordinator = _SingletonCoordinator()  # _active == 0
    runner = _make_runner(_AdmissionGateConfig(process_count_gate_enabled=True, max_descendant_processes=2), coordinator)
    assert runner._await_admission(lambda: False) is True


def test_process_gate_blocks_then_admits(monkeypatch):
    counts = [10, 10, 1]  # over ceiling twice, then drops below

    def fake_count(pid):
        return counts.pop(0) if len(counts) > 1 else counts[0]

    monkeypatch.setattr(pytest_runner, "subtree_process_count", fake_count)
    coordinator = _SingletonCoordinator()
    coordinator.acquire_normal(lambda: False, 0.01)  # _active == 1, so min-1 does not short-circuit
    runner = _make_runner(_AdmissionGateConfig(process_count_gate_enabled=True, max_descendant_processes=2), coordinator)
    assert runner._await_admission(lambda: False) is True
    assert counts == [1], "expected the gate to poll until the count dropped below the ceiling"


def test_gate_aborts_when_should_abort(monkeypatch):
    monkeypatch.setattr(pytest_runner, "subtree_process_count", lambda pid: 999)
    coordinator = _SingletonCoordinator()
    coordinator.acquire_normal(lambda: False, 0.01)  # _active == 1, gate genuinely blocks
    runner = _make_runner(_AdmissionGateConfig(process_count_gate_enabled=True, max_descendant_processes=2), coordinator)

    calls = {"n": 0}

    def should_abort():
        calls["n"] += 1
        return calls["n"] > 1  # abort on the second check

    assert runner._await_admission(should_abort) is False


def test_commit_gate_composes_as_and(monkeypatch):
    # Process gate passes, commit gate blocks -> overall block (until min-1 / abort).
    monkeypatch.setattr(pytest_runner, "subtree_process_count", lambda pid: 1)
    monkeypatch.setattr(pytest_runner, "commit_charge_and_limit", lambda: (95, 100))  # 95% > 90% threshold
    coordinator = _SingletonCoordinator()
    coordinator.acquire_normal(lambda: False, 0.01)
    runner = _make_runner(
        _AdmissionGateConfig(process_count_gate_enabled=True, max_descendant_processes=10, commit_gate_enabled=True, commit_gate_threshold=0.90),
        coordinator,
    )
    calls = {"n": 0}

    def should_abort():
        calls["n"] += 1
        return calls["n"] > 1

    assert runner._await_admission(should_abort) is False  # commit gate kept it blocked


def test_commit_gate_fails_open_when_unavailable(monkeypatch):
    monkeypatch.setattr(pytest_runner, "commit_charge_and_limit", lambda: None)  # signal unavailable
    runner = _make_runner(_AdmissionGateConfig(commit_gate_enabled=True, commit_gate_threshold=0.90))
    assert runner._await_admission(lambda: False) is True


def test_process_gate_fails_open_on_read_error(monkeypatch):
    monkeypatch.setattr(pytest_runner, "subtree_process_count", lambda pid: 0)  # 0 == read failure
    runner = _make_runner(_AdmissionGateConfig(process_count_gate_enabled=True, max_descendant_processes=2))
    assert runner._await_admission(lambda: False) is True
