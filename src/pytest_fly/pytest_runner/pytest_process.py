"""
Single-test subprocess — runs one pytest module with coverage collection
and a :class:`ProcessMonitor` that samples CPU/memory usage.
"""

import contextlib
import logging
import shutil
import time
import traceback
from multiprocessing import Process
from pathlib import Path
from queue import Empty

import psutil
import pytest
from coverage import Coverage
from typeguard import typechecked

from ..__version__ import application_name
from ..db import PytestProcessInfoDB
from ..file_util import sanitize_test_name
from ..interfaces import PyTestFlyExitCode, PytestProcessInfo, int_exit_code_to_pytest_fly_exit_code
from ..logger import configure_child_logger, get_logger
from .live_output import live_output_path
from .process_monitor import ProcessMonitor

log = get_logger(application_name)


@typechecked()
def terminate_process_tree(pid: int | None, terminate_timeout: float = 3.0, kill_timeout: float = 2.0, reap_parent: bool = True) -> None:
    """
    Terminate a process and all of its descendants.

    Tests under test may spawn their own subprocesses (subprocess.Popen, multiprocessing,
    helper services). When we kill only the direct pytest subprocess those descendants
    are orphaned. This helper walks the process tree via psutil and kills everything.

    Algorithm: SIGTERM children-first then parent (so the parent can't keep spawning
    new children between enumeration and signal); wait; re-scan for grandchildren that
    appeared in the gap; SIGKILL survivors.

    Cross-platform via psutil — on Windows ``terminate()`` and ``kill()`` both map to
    ``TerminateProcess``; on POSIX they map to SIGTERM and SIGKILL.

    :param pid: PID of the parent process to terminate. ``None`` is a no-op.
    :param terminate_timeout: Seconds to wait after SIGTERM before escalating to SIGKILL.
    :param kill_timeout: Seconds to wait after SIGKILL for the OS to reap the processes.
    :param reap_parent: When ``True`` (default), ``psutil.wait_procs`` waits on the
        parent too, which on POSIX reaps the zombie via ``os.waitpid``. Set to
        ``False`` when the caller owns the parent's lifecycle and will reap it
        itself (e.g. a ``multiprocessing.Process`` reaped via ``join()``).
        Reaping a multiprocessing child here leaves its wrapper in a permanently
        "alive" state — its own ``os.waitpid`` then raises ``ChildProcessError``,
        ``_popen.poll()`` returns ``None``, and ``is_alive()`` returns ``True``
        forever.
    """
    if pid is None:
        return

    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return

    log.info(f"terminating process tree for pid={pid}")

    try:
        descendants = parent.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        descendants = []

    # SIGTERM children first, then parent
    for proc in descendants + [parent]:
        try:
            proc.terminate()
            log.debug(f"terminated pid={proc.pid} name={proc.name()}")
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            log.debug(f"could not terminate pid={proc.pid}: {e}")

    wait_targets = descendants + [parent] if reap_parent else descendants
    _, alive = psutil.wait_procs(wait_targets, timeout=terminate_timeout)

    # Re-scan for grandchildren that appeared between snapshot and SIGTERM
    try:
        if parent.is_running():
            new_descendants = parent.children(recursive=True)
            seen_pids = {p.pid for p in alive}
            for proc in new_descendants:
                if proc.pid not in seen_pids:
                    alive.append(proc)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    # When not reaping the parent we still want to ensure it gets SIGKILL'd if
    # SIGTERM didn't take; do it best-effort without waiting/reaping.
    if not reap_parent:
        try:
            if parent.is_running():
                try:
                    parent.kill()
                    log.debug(f"killed parent pid={parent.pid}")
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    log.debug(f"could not kill parent pid={parent.pid}: {e}")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if not alive:
        return

    # SIGKILL survivors, children-first when the parent is in scope
    if reap_parent:
        survivors_children_first = [p for p in alive if p.pid != pid] + [p for p in alive if p.pid == pid]
    else:
        survivors_children_first = list(alive)
    for proc in survivors_children_first:
        try:
            proc.kill()
            log.debug(f"killed pid={proc.pid}")
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            log.debug(f"could not kill pid={proc.pid}: {e}")

    _, still_alive = psutil.wait_procs(survivors_children_first, timeout=kill_timeout)
    for proc in still_alive:
        try:
            log.warning(f"process did not die after kill: pid={proc.pid} name={proc.name()}")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            log.warning(f"process did not die after kill: pid={proc.pid}")


class PytestProcess(Process):
    """
    A process that performs a pytest run.
    """

    @typechecked()
    def __init__(self, run_guid: str, test: Path | str, data_dir: Path, update_rate: float, put_version: str = "", put_fingerprint: str = "") -> None:
        """
        Pytest process for a single pytest test.

        :param run_guid: the pytest run this process is associated with (same GUID for all tests in a pytest run)
        :param test: the test to run
        :param data_dir: the directory to store coverage data in
        :param update_rate: the update rate for the process monitor
        :param put_version: display label for the program under test (stamped on each DB record)
        :param put_fingerprint: program-under-test fingerprint for RunMode.CHECK comparison
        """
        super().__init__(name=str(test))
        self.data_dir = data_dir
        self.run_guid = run_guid
        self.update_rate = update_rate
        self.put_version = put_version
        self.put_fingerprint = put_fingerprint

        self._process_monitor_process = None

    def run(self) -> None:

        configure_child_logger(f"{sanitize_test_name(self.name)}.log")

        # start the process monitor to monitor things like CPU and memory usage
        self._process_monitor_process = ProcessMonitor(self.run_guid, self.name, self.pid, self.update_rate)
        self._process_monitor_process.start()

        # update the pytest process info to show that the test is running
        with PytestProcessInfoDB(self.data_dir) as db:
            pytest_process_info = PytestProcessInfo(
                self.run_guid,
                self.name,
                self.pid,
                PyTestFlyExitCode.NONE,
                None,
                time_stamp=time.time(),
                put_version=self.put_version,
                put_fingerprint=self.put_fingerprint,
            )
            db.write(pytest_process_info)

        # Finally, actually run pytest!
        # Redirect stdout and stderr into a per-test log file so the GUI can tail live output
        # while the test is running.  The file is line-buffered; ``-s`` (below) disables
        # pytest's own capture so prints stream immediately.
        live_path = live_output_path(self.data_dir, self.name)
        live_path.parent.mkdir(parents=True, exist_ok=True)
        live_path.unlink(missing_ok=True)
        with open(live_path, "w", buffering=1, encoding="utf-8", errors="replace", newline="") as live_file:
            with contextlib.redirect_stdout(live_file), contextlib.redirect_stderr(live_file):
                # create a temp coverage file and then move it so if the file exists, the content is complete (the save is not necessarily instantaneous and atomic)
                coverage_dir = Path(self.data_dir, "coverage")
                coverage_dir.mkdir(parents=True, exist_ok=True)
                safe_name = sanitize_test_name(self.name)
                coverage_file_path = Path(coverage_dir, f"{safe_name}.coverage")
                coverage_temp_file_path = Path(coverage_dir, f"{safe_name}.temp")
                coverage_temp_file_path.unlink(missing_ok=True)
                coverage = Coverage(coverage_temp_file_path)
                coverage.start()

                try:
                    # -rA: show full short test summary (all outcomes, untruncated assertion messages)
                    # -s: disable pytest capture so stdout/stderr stream live to the log file
                    pytest_exit_code = pytest.main([self.name, "-rA", "-s"])
                    exit_code = int_exit_code_to_pytest_fly_exit_code(pytest_exit_code)
                except Exception:
                    exit_code = PyTestFlyExitCode.INTERNAL_ERROR
                    try:
                        live_file.write(f"\n\npytest.main raised an exception:\n{traceback.format_exc()}")
                    except (ValueError, OSError):
                        pass  # live_file may be closed if the test redirected/closed stderr

                coverage.stop()
                coverage.save()
                coverage_file_path.unlink(missing_ok=True)
                shutil.move(coverage_temp_file_path, coverage_file_path)

        output: str = live_path.read_text(encoding="utf-8", errors="replace")

        # Tests may have registered StreamHandlers pointing to live_file (now closed).
        # Remove them so subsequent log calls don't raise ValueError.
        for _lgr in [logging.root, *logging.Logger.manager.loggerDict.values()]:
            if isinstance(_lgr, logging.Logger):
                for _handler in list(_lgr.handlers):
                    if hasattr(_handler, "stream") and getattr(_handler.stream, "closed", False):
                        _lgr.removeHandler(_handler)

        # Stop the monitor and drain its queue while it exits. Draining as the
        # producer shuts down keeps the OS pipe from filling, which would otherwise
        # block the monitor's feeder thread and hang its process exit.
        self._process_monitor_process.request_stop()
        cpu_samples = []
        memory_samples = []
        commit_samples = []
        drain_deadline = time.time() + 100.0
        while True:
            try:
                monitor_info = self._process_monitor_process.process_monitor_queue.get(timeout=0.1)
                if monitor_info.cpu_percent is not None:
                    cpu_samples.append(monitor_info.cpu_percent)
                if monitor_info.memory_percent is not None:
                    memory_samples.append(monitor_info.memory_percent)
                if monitor_info.commit_bytes is not None:
                    commit_samples.append(monitor_info.commit_bytes)
            except Empty:
                if not self._process_monitor_process.is_alive():
                    break
                if time.time() >= drain_deadline:
                    break
        self._process_monitor_process.join(5.0)
        if self._process_monitor_process.is_alive():
            log.warning(f"{self._process_monitor_process} is alive")
            self._process_monitor_process.kill()
            self._process_monitor_process.join(5.0)
        peak_cpu = max(cpu_samples) if cpu_samples else None
        peak_memory = max(memory_samples) if memory_samples else None
        peak_commit = max(commit_samples) if commit_samples else None

        # update the pytest process info to show that the test has finished
        with PytestProcessInfoDB(self.data_dir) as db:
            pytest_process_info = PytestProcessInfo(
                self.run_guid,
                self.name,
                self.pid,
                exit_code,
                output,
                time.time(),
                peak_cpu,
                peak_memory,
                put_version=self.put_version,
                put_fingerprint=self.put_fingerprint,
                commit_bytes=peak_commit,
            )
            db.write(pytest_process_info)

        log.debug(f"{self.name=},{self.name},{exit_code=},{output=}")
