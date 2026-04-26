import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import psutil

from pytest_fly.db import PytestProcessInfoDB
from pytest_fly.guid import generate_uuid
from pytest_fly.interfaces import PyTestFlyExitCode
from pytest_fly.pytest_runner.pytest_process import PytestProcess, terminate_process_tree


def test_pytest_process():
    with TemporaryDirectory() as data_dir:
        run_uuid = generate_uuid()
        pytest_process = PytestProcess(run_uuid, Path("tests/test_no_operation.py"), Path(data_dir), 3.0)
        pytest_process.start()
        pytest_process.join()

        with PytestProcessInfoDB(Path(data_dir)) as db:
            results = db.query(run_uuid)
            assert len(results) >= 2  # at least start and end entries

        assert len(results) >= 2
        assert results[-1].exit_code == PyTestFlyExitCode.OK
        execution_time = results[-1].time_stamp - results[0].time_stamp
        print(f"{execution_time=}")
        assert execution_time >= 0.0  # 1.4768257141113281 has been observed


def _wait_pid_gone(pid: int, timeout: float = 5.0) -> bool:
    """Poll until *pid* no longer exists (Windows handle cleanup is async)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not psutil.pid_exists(pid):
            return True
        time.sleep(0.1)
    return not psutil.pid_exists(pid)


def test_terminate_process_tree_none_pid():
    # no-op, must not raise
    terminate_process_tree(None)


def test_terminate_process_tree_already_dead():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=10.0)
    # the pid is now reaped/gone - helper must handle gracefully
    terminate_process_tree(proc.pid)


def test_terminate_process_tree_no_children():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        terminate_process_tree(proc.pid)
        assert _wait_pid_gone(proc.pid)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5.0)


def test_terminate_process_tree_kills_children():
    # Parent spawns a long-sleeping child and prints the child PID, then sleeps itself.
    code = f"import subprocess, sys, time;c = subprocess.Popen([{sys.executable!r}, '-c', 'import time; time.sleep(60)']);print(c.pid, flush=True);time.sleep(60)"
    parent = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        # read the child pid line that the parent printed
        line = parent.stdout.readline().strip()
        child_pid = int(line)
        # sanity: both must be alive before we kill the tree
        assert psutil.pid_exists(parent.pid)
        assert psutil.pid_exists(child_pid)

        terminate_process_tree(parent.pid)

        assert _wait_pid_gone(parent.pid), f"parent pid {parent.pid} still alive"
        assert _wait_pid_gone(child_pid), f"child pid {child_pid} still alive"
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5.0)


def test_terminate_process_tree_idempotent():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        terminate_process_tree(proc.pid)
        assert _wait_pid_gone(proc.pid)
        # second call after the process is gone must be a graceful no-op
        terminate_process_tree(proc.pid)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5.0)
