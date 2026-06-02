"""Part A — reap_pids: orphan reaping after a test exits on its own.

Verifies that snapshot survivors are killed, a clean test kills nothing, the PID-reuse
(create_time) guard protects unrelated processes, and a raising psutil call fails open.
"""

import subprocess
import sys
import time

import psutil

from pytest_fly.pytest_runner import pytest_process
from pytest_fly.pytest_runner.pytest_process import reap_pids


def _spawn_sleeper() -> subprocess.Popen:
    """Spawn a child process that sleeps long enough to be reaped during the test."""
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])


def _wait_dead(pid: int, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not psutil.pid_exists(pid):
            return True
        time.sleep(0.05)
    return False


def test_reap_kills_snapshot_survivors():
    proc = _spawn_sleeper()
    try:
        create_time = psutil.Process(proc.pid).create_time()
        reap_pids({(proc.pid, create_time)})
        assert _wait_dead(proc.pid), "expected the orphaned process to be killed"
    finally:
        if psutil.pid_exists(proc.pid):
            proc.kill()
        proc.wait(timeout=5)


def test_reap_empty_snapshot_is_noop():
    # A clean test leaves no descendants — nothing to do, and no error.
    reap_pids(set())


def test_reap_pid_reuse_guard_spares_mismatched_create_time():
    proc = _spawn_sleeper()
    try:
        real_create_time = psutil.Process(proc.pid).create_time()
        # A snapshot entry whose create_time no longer matches the live PID must NOT be killed.
        reap_pids({(proc.pid, real_create_time + 1000.0)})
        time.sleep(0.5)
        assert psutil.pid_exists(proc.pid), "PID-reuse guard should have spared the process"
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_reap_fails_open_on_raising_psutil(monkeypatch):
    monkeypatch.setattr(pytest_process, "_reap_warned_once", False)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated psutil failure")

    monkeypatch.setattr(pytest_process.psutil, "Process", boom)
    # Must not raise even though every psutil call explodes.
    reap_pids({(12345, 1.0)})
    assert pytest_process._reap_warned_once is True
