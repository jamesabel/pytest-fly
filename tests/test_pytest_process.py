import builtins
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import psutil

from pytest_fly.db import PytestProcessInfoDB
from pytest_fly.guid import generate_uuid
from pytest_fly.interfaces import PyTestFlyExitCode
from pytest_fly.pytest_runner.live_output import live_output_path
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


def _make_process(data_dir: str) -> PytestProcess:
    return PytestProcess(generate_uuid(), Path("tests/test_no_operation.py"), Path(data_dir), 3.0)


def test_open_live_output_truncates_existing_content():
    """The canonical path is opened in 'w' mode, truncating any stale content."""
    with TemporaryDirectory() as data_dir:
        process = _make_process(data_dir)
        live_path = live_output_path(Path(data_dir), process.name)
        live_path.parent.mkdir(parents=True, exist_ok=True)
        live_path.write_text("stale content from a previous run\n")

        live_file, actual_path = process._open_live_output(live_path)
        with live_file:
            live_file.write("fresh\n")
        assert actual_path == live_path
        assert live_path.read_text() == "fresh\n"  # stale content was truncated


def test_open_live_output_retries_then_succeeds(monkeypatch):
    """A briefly-locked canonical path is retried and then opened successfully (no fallback)."""
    with TemporaryDirectory() as data_dir:
        process = _make_process(data_dir)
        live_path = live_output_path(Path(data_dir), process.name)
        live_path.parent.mkdir(parents=True, exist_ok=True)

        real_open = builtins.open
        calls = {"n": 0}

        def flaky_open(file, *args, **kwargs):
            if Path(file) == live_path and calls["n"] < 2:
                calls["n"] += 1
                raise PermissionError(32, "locked")
            return real_open(file, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", flaky_open)
        live_file, actual_path = process._open_live_output(live_path, retry_timeout=5.0, retry_interval=0.01)
        with live_file:
            live_file.write("ok\n")
        assert actual_path == live_path  # recovered on the canonical path
        assert calls["n"] == 2  # two failures then success


def test_open_live_output_falls_back_when_persistently_locked(monkeypatch):
    """A persistently-locked canonical path falls back to a pid-unique sibling instead of raising."""
    with TemporaryDirectory() as data_dir:
        process = _make_process(data_dir)
        live_path = live_output_path(Path(data_dir), process.name)
        live_path.parent.mkdir(parents=True, exist_ok=True)

        real_open = builtins.open

        def locked_open(file, *args, **kwargs):
            if Path(file) == live_path:
                raise PermissionError(32, "locked")
            return real_open(file, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", locked_open)
        live_file, actual_path = process._open_live_output(live_path, retry_timeout=0.05, retry_interval=0.01)
        with live_file:
            live_file.write("fallback\n")
        assert actual_path != live_path  # used the fallback sibling
        assert actual_path.parent == live_path.parent
        assert actual_path.suffix == live_path.suffix  # still a .log file
        assert actual_path.read_text() == "fallback\n"


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
