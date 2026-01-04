from pathlib import Path
from queue import Queue, Empty
from typing import Optional
from threading import Event, Thread
from collections import defaultdict
import time

from typeguard import typechecked
from PySide6.QtGui import QColor

from ..logger import get_logger
from ..interfaces import ScheduledTests, PytestRunnerState, PyTestFlyExitCode
from .pytest_process import PytestProcess, PytestProcessInfo
from ..db import PytestProcessInfoDB
from .const import TIMEOUT

log = get_logger()


class PytestRunState:
    """
    Convert a list of PytestProcessInfo objects to a PytestRunnerState object.
    """

    @typechecked()
    def __init__(self, run_infos: list[PytestProcessInfo]):
        if len(run_infos) > 0:
            last_run_info = run_infos[-1]
            self.name = last_run_info.name

            exit_code = last_run_info.exit_code
            if exit_code == PyTestFlyExitCode.OK:
                self.state = PytestRunnerState.PASS
            elif PyTestFlyExitCode.OK < exit_code <= PyTestFlyExitCode.MAX_PYTEST_EXIT_CODE:
                # any pytest exit code other than OK is a failure
                self.state = PytestRunnerState.FAIL
            elif exit_code == PyTestFlyExitCode.TERMINATED:
                self.state = PytestRunnerState.TERMINATED
            elif exit_code == PyTestFlyExitCode.NONE:
                if last_run_info.pid is None:
                    self.state = PytestRunnerState.QUEUED
                else:
                    self.state = PytestRunnerState.RUNNING
            else:
                log.error(f"unknown exit code {exit_code} for test {self.name}, defaulting to QUEUED")
                self.state = PytestRunnerState.QUEUED
        else:
            self.name = None
            self.state = PytestRunnerState.QUEUED

    @typechecked()
    def get_state(self) -> PytestRunnerState:
        return self.state

    @typechecked()
    def get_string(self) -> str:
        return self.state.value

    def get_name(self) -> str | None:
        return self.name

    @typechecked()
    def get_qt_color(self) -> QColor:
        state_to_color = {
            PytestRunnerState.QUEUED: QColor("blue"),
            PytestRunnerState.RUNNING: QColor("gray"),
            PytestRunnerState.PASS: QColor("green"),
            PytestRunnerState.FAIL: QColor("red"),
            PytestRunnerState.TERMINATED: QColor("orange"),
        }
        color = state_to_color[self.state]
        return color


class PytestRunner(Thread):

    @typechecked()
    def __init__(self, run_guid: str, tests: ScheduledTests, number_of_processes: int, data_dir: Path, update_rate: float):
        self.run_guid = run_guid
        self.tests = tests
        self.number_of_processes = number_of_processes
        self.data_dir = data_dir
        self.update_rate = update_rate

        self._test_runners = {}
        self._results = defaultdict(list)
        self._started_event = Event()
        self._written_to_db = set()

        super().__init__()

    def run(self):

        test_queue = Queue()
        with PytestProcessInfoDB(self.data_dir) as db:
            for test in self.tests:
                test_queue.put(test.node_id)
                pytest_process_info = PytestProcessInfo(self.run_guid, test.node_id, None, PyTestFlyExitCode.NONE, None, time_stamp=time.time())  # queued
                db.write(pytest_process_info)

        for thread_number in range(self.number_of_processes):
            test_runner = _TestRunner(self.run_guid, test_queue, self.data_dir, self.update_rate)
            test_runner.start()
            self._test_runners[thread_number] = test_runner
        self._started_event.set()

    def is_running(self) -> bool:
        running = []
        for test_runner in self._test_runners.values():
            if test_runner.process is not None:
                running.append(test_runner.process.is_alive())
        return any(running)

    @typechecked()
    def join(self, timeout_seconds: float | None = None) -> bool:

        # in case join is called right after .start(), wait until .run() has started all workers
        start = time.time()
        while not self._started_event.is_set() and time.time() - start < timeout_seconds:
            time.sleep(0.1)

        finished = []
        for test_runner in self._test_runners.values():
            finished.append(test_runner.join(timeout_seconds))
        return all(finished)

    def stop(self):
        try:
            for test_runner in self._test_runners.values():
                test_runner.stop()
        except (OSError, RuntimeError, PermissionError) as e:
            log.error(f"error stopping pytest runner,{self.run_guid=},{e}", exc_info=True, stack_info=True)


class _TestRunner(Thread):
    """
    Worker that runs pytest tests in separate processes.
    """

    @typechecked()
    def __init__(self, run_guid: str, pytest_test_queue: Queue, data_dir: Path, update_rate: float) -> None:
        """
        Pytest runner worker.
        """
        super().__init__()

        self.run_guid = run_guid
        self.pytest_test_queue = pytest_test_queue
        self.data_dir = data_dir
        self.update_rate = update_rate  # for the process monitor

        self.process: Optional[PytestProcess] | None = None
        self._stop_event = Event()

    def run(self):

        while not self._stop_event.is_set():
            try:
                test = self.pytest_test_queue.get(False)
            except Empty:
                test = None

            if test is None:
                break

            self.process = PytestProcess(self.run_guid, test, self.data_dir, self.update_rate)
            log.info(f'Starting process for test "{test}" ({self.run_guid=})')
            self.process.start()

            # facilitate stopping the process if needed
            while self.process.is_alive():
                if self._stop_event.is_set():
                    try:
                        proc = self.process
                        proc_name = getattr(proc, "name", "<unknown>")
                    except (OSError, RuntimeError, PermissionError) as e:
                        log.warning(f"error accessing process name,{self.run_guid=},{e}")
                        proc = None
                        proc_name = None

                    # Try polite shutdown first
                    if proc is None:
                        log.info(f"{proc=},cannot terminate or kill ({self.run_guid=})")
                    else:
                        try:
                            proc.terminate()
                            log.info(f'attempted terminate for process "{proc_name}" ({self.run_guid=})')
                        except (OSError, RuntimeError, PermissionError) as e:
                            log.info(f'error calling terminate on "{proc_name}",{self.run_guid=},{e}')

                        proc.join(max(self.update_rate, 2.0))  # Wait a short grace period for the process to exit

                        if not proc.is_alive():
                            log.info(f'process for test "{proc_name}" terminated ({self.run_guid=})')
                            with PytestProcessInfoDB(self.data_dir) as db:
                                pytest_process_info = PytestProcessInfo(self.run_guid, test, None, PyTestFlyExitCode.TERMINATED, None, time_stamp=time.time())  # queued
                                db.write(pytest_process_info)
                        else:
                            # Ensure we are still operating on the same process object before forcing kill
                            if self.process is not proc:
                                log.info(f'process object changed while waiting; skipping kill for "{proc_name}" ({self.run_guid=})')
                            else:
                                try:
                                    proc.kill()
                                    log.info(f'process for test "{proc_name}" killed ({self.run_guid=})')
                                except (OSError, RuntimeError, PermissionError) as e:
                                    log.warning(f'error calling kill on "{proc_name}",{self.run_guid=},{e}')

                # Regular join / polling to avoid busy loop
                if self.process is None:
                    time.sleep(self.update_rate)
                else:
                    self.process.join(self.update_rate)

            self.process.join(TIMEOUT)  # should already be done, but just in case
            if self.process.is_alive():
                log.warning(f'process for test "{self.process.name}" did not terminate ({self.run_guid=})')
            else:
                log.info(f'process for test "{self.process.name}" completed ({self.run_guid=})')

    def stop(self):
        self._stop_event.set()
