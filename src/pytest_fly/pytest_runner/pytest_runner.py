import time
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Optional

from PySide6.QtGui import QColor
from typeguard import typechecked

from ..colors import BAR_COLORS, TABLE_COLORS
from ..db import PytestProcessInfoDB
from ..interfaces import PyTestFlyExitCode, PytestRunnerState, ScheduledTest
from ..logger import get_logger
from .const import TIMEOUT
from .pytest_process import PytestProcess, PytestProcessInfo

log = get_logger()


class PytestRunState:
    """
    Convert a list of PytestProcessInfo objects to a PytestRunnerState object.
    """

    @typechecked()
    def __init__(self, run_infos: list[PytestProcessInfo]):
        if len(run_infos) > 0:
            last_run_info = run_infos[-1]
            self._name = last_run_info.name

            exit_code = last_run_info.exit_code
            if exit_code == PyTestFlyExitCode.OK:
                self._state = PytestRunnerState.PASS
            elif PyTestFlyExitCode.OK < exit_code <= PyTestFlyExitCode.MAX_PYTEST_EXIT_CODE:
                # any pytest exit code other than OK is a failure
                self._state = PytestRunnerState.FAIL
            elif exit_code == PyTestFlyExitCode.TERMINATED:
                self._state = PytestRunnerState.TERMINATED
            elif exit_code == PyTestFlyExitCode.STOPPED:
                self._state = PytestRunnerState.STOPPED
            elif exit_code == PyTestFlyExitCode.NONE:
                if last_run_info.pid is None:
                    self._state = PytestRunnerState.QUEUED
                else:
                    self._state = PytestRunnerState.RUNNING
            else:
                log.error(f"unknown exit code {exit_code} for test {self._name}, defaulting to QUEUED")
                self._state = PytestRunnerState.QUEUED
        else:
            self._name = None
            self._state = PytestRunnerState.QUEUED

    @typechecked()
    def get_state(self) -> PytestRunnerState:
        return self._state

    @typechecked()
    def get_string(self) -> str:
        return self._state.value

    def get_name(self) -> str | None:
        return self._name

    @typechecked()
    def get_qt_bar_color(self) -> QColor:
        """Return the color used for progress-bar visualization of this state."""
        return BAR_COLORS[self._state]

    @typechecked()
    def get_qt_table_color(self) -> QColor:
        """Return the foreground text color used in the table view for this state."""
        return TABLE_COLORS[self._state]


class PytestRunner(Thread):
    """
    Orchestrates parallel test execution by spawning a pool of :class:`_TestRunner`
    worker threads that each pull tests from a shared queue.
    """

    @typechecked()
    def __init__(self, run_guid: str, tests: list[ScheduledTest], number_of_processes: int, data_dir: Path, update_rate: float):
        self.run_guid = run_guid
        self.tests = tests
        self.number_of_processes = number_of_processes
        self.data_dir = data_dir
        self.update_rate = update_rate

        self._test_runners = {}
        self._started_event = Event()
        self._written_to_db = set()

        super().__init__()

    def run(self):
        """Enqueue all tests, spin up worker threads, and signal readiness."""

        test_queue = Queue()
        with PytestProcessInfoDB(self.data_dir) as db:
            for test in self.tests:
                test_queue.put(test)
                pytest_process_info = PytestProcessInfo(self.run_guid, test.node_id, None, PyTestFlyExitCode.NONE, None, time_stamp=time.time())  # queued
                db.write(pytest_process_info)

        # Singleton enforcement primitives (shared across all workers)
        singleton_event = Event()
        singleton_event.set()  # parallel execution allowed initially
        active_count_lock = Lock()
        active_workers = [0]  # mutable counter shared by reference
        all_idle_event = Event()
        all_idle_event.set()  # no workers active initially

        for thread_number in range(self.number_of_processes):
            test_runner = _TestRunner(self.run_guid, test_queue, self.data_dir, self.update_rate, singleton_event, active_count_lock, active_workers, all_idle_event)
            test_runner.start()
            self._test_runners[thread_number] = test_runner
        self._started_event.set()

    def is_running(self) -> bool:
        """Return ``True`` if any worker thread is still alive."""
        return any(test_runner.is_alive() for test_runner in self._test_runners.values())

    @typechecked()
    def join(self, timeout_seconds: float | None = None) -> bool:

        # in case join is called right after .start(), wait until .run() has started all workers
        if timeout_seconds is not None:
            start = time.time()
            while not self._started_event.is_set() and time.time() - start < timeout_seconds:
                time.sleep(0.1)
        else:
            self._started_event.wait()

        for test_runner in self._test_runners.values():
            test_runner.join(timeout_seconds)
        return all(not test_runner.is_alive() for test_runner in self._test_runners.values())

    def stop(self):
        try:
            for test_runner in self._test_runners.values():
                test_runner.stop()
        except (OSError, RuntimeError, PermissionError) as e:
            log.error(f"error stopping pytest runner,{self.run_guid=},{e}", exc_info=True, stack_info=True)

    def soft_stop(self):
        """Signal workers to finish their current test and stop picking up new ones."""
        try:
            for test_runner in self._test_runners.values():
                test_runner.soft_stop()
        except (OSError, RuntimeError, PermissionError) as e:
            log.error(f"error soft-stopping pytest runner,{self.run_guid=},{e}", exc_info=True, stack_info=True)


class _TestRunner(Thread):
    """
    Worker thread that pulls tests from a shared queue and runs each one
    in a dedicated :class:`PytestProcess`.  Singleton tests are run exclusively —
    no other workers execute concurrently.
    """

    @typechecked()
    def __init__(
        self,
        run_guid: str,
        pytest_test_queue: Queue,
        data_dir: Path,
        update_rate: float,
        singleton_event: Event,
        active_count_lock: Lock,
        active_workers: list,
        all_idle_event: Event,
    ) -> None:
        """
        :param run_guid: GUID identifying the overall test run.
        :param pytest_test_queue: Shared queue of :class:`ScheduledTest` to execute.
        :param data_dir: Directory used for the results database.
        :param update_rate: Polling / process-monitor sample interval in seconds.
        :param singleton_event: Cleared when a singleton is running to block other workers.
        :param active_count_lock: Protects the *active_workers* counter.
        :param active_workers: Single-element list ``[int]`` tracking how many workers are executing.
        :param all_idle_event: Set when *active_workers* drops to zero.
        """
        super().__init__()

        self.run_guid = run_guid
        self.pytest_test_queue = pytest_test_queue
        self.data_dir = data_dir
        self.update_rate = update_rate

        self.process: Optional[PytestProcess] = None
        self._stop_event = Event()
        self._soft_stop_event = Event()

        # Singleton enforcement (shared across all workers)
        self._singleton_event = singleton_event
        self._active_count_lock = active_count_lock
        self._active_workers = active_workers
        self._all_idle_event = all_idle_event

    # ------------------------------------------------------------------
    # Active-worker tracking
    # ------------------------------------------------------------------

    def _increment_active(self):
        """Mark this worker as actively running a test."""
        with self._active_count_lock:
            self._active_workers[0] += 1
            self._all_idle_event.clear()

    def _decrement_active(self):
        """Mark this worker as idle.  Signals *all_idle_event* when count hits zero."""
        with self._active_count_lock:
            self._active_workers[0] -= 1
            if self._active_workers[0] == 0:
                self._all_idle_event.set()

    # ------------------------------------------------------------------
    # Process lifecycle helpers
    # ------------------------------------------------------------------

    def _terminate_process(self, proc: PytestProcess, proc_name: str, test: str) -> None:
        """
        Attempt a graceful termination of *proc*.  If the process exits within
        a short grace period the result is recorded as ``TERMINATED`` in the DB.
        Otherwise :meth:`_force_kill_process` is called.

        :param proc: The running :class:`PytestProcess`.
        :param proc_name: Human-readable name for log messages.
        :param test: Test node-ID (used when writing the DB record).
        """
        try:
            proc.terminate()
            log.info(f'attempted terminate for process "{proc_name}" ({self.run_guid=})')
        except (OSError, RuntimeError, PermissionError) as e:
            log.info(f'error calling terminate on "{proc_name}",{self.run_guid=},{e}')

        proc.join(max(self.update_rate, 2.0))

        if not proc.is_alive():
            log.info(f'process for test "{proc_name}" terminated ({self.run_guid=})')
            with PytestProcessInfoDB(self.data_dir) as db:
                info = PytestProcessInfo(self.run_guid, test, None, PyTestFlyExitCode.TERMINATED, None, time_stamp=time.time())
                db.write(info)
        else:
            self._force_kill_process(proc, proc_name)

    def _force_kill_process(self, proc: PytestProcess, proc_name: str) -> None:
        """
        Forcefully kill *proc* after a graceful terminate failed.

        A safety check ensures the ``self.process`` reference has not been
        replaced by a newer process before issuing the kill.

        :param proc: The process to kill.
        :param proc_name: Human-readable name for log messages.
        """
        if self.process is not proc:
            log.info(f'process object changed while waiting; skipping kill for "{proc_name}" ({self.run_guid=})')
            return
        try:
            proc.kill()
            log.info(f'process for test "{proc_name}" killed ({self.run_guid=})')
        except (OSError, RuntimeError, PermissionError) as e:
            log.warning(f'error calling kill on "{proc_name}",{self.run_guid=},{e}')

    def _handle_stop_request(self, test: str) -> None:
        """
        Called inside the polling loop when a stop has been requested.
        Resolves the current process reference and delegates to
        :meth:`_terminate_process`.

        :param test: Test node-ID currently being executed.
        """
        try:
            proc = self.process
            proc_name = getattr(proc, "name", "<unknown>")
        except (OSError, RuntimeError, PermissionError) as e:
            log.warning(f"error accessing process name,{self.run_guid=},{e}")
            proc = None
            proc_name = None

        if proc is None:
            log.info(f"{proc=},cannot terminate or kill ({self.run_guid=})")
        else:
            self._terminate_process(proc, proc_name, test)

    # ------------------------------------------------------------------
    # Test execution
    # ------------------------------------------------------------------

    def _run_single_test(self, test: str):
        """Run a single test process, tracking the active worker count."""

        self._increment_active()
        try:
            self.process = PytestProcess(self.run_guid, test, self.data_dir, self.update_rate)
            log.info(f'Starting process for test "{test}" ({self.run_guid=})')
            self.process.start()

            while self.process.is_alive():
                if self._stop_event.is_set():
                    self._handle_stop_request(test)

                # Poll / yield to avoid busy-looping
                if self.process is None:
                    time.sleep(self.update_rate)
                else:
                    self.process.join(self.update_rate)

            self.process.join(TIMEOUT)  # should already be done, but just in case
            if self.process.is_alive():
                log.warning(f'process for test "{self.process.name}" did not terminate ({self.run_guid=})')
            else:
                log.info(f'process for test "{self.process.name}" completed ({self.run_guid=})')
        finally:
            self._decrement_active()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self):
        """Consume tests from the queue until it is empty or a stop is requested."""

        while not self._stop_event.is_set() and not self._soft_stop_event.is_set():
            try:
                scheduled_test = self.pytest_test_queue.get(False)
            except Empty:
                break

            test = scheduled_test.node_id

            if scheduled_test.singleton:
                # Singleton protocol: block others, drain active workers, run exclusively, resume.
                self._singleton_event.clear()
                while not self._all_idle_event.wait(timeout=self.update_rate):
                    if self._stop_event.is_set() or self._soft_stop_event.is_set():
                        break
                if self._stop_event.is_set():
                    self._handle_stop_request(test)
                    break
                if self._soft_stop_event.is_set():
                    self._singleton_event.set()
                    self._drain_queue()
                    break
                log.info(f'Running singleton test "{test}" ({self.run_guid=})')
                self._run_single_test(test)
                self._singleton_event.set()
            else:
                # Normal protocol: wait until no singleton is running.
                while not self._singleton_event.wait(timeout=self.update_rate):
                    if self._stop_event.is_set() or self._soft_stop_event.is_set():
                        break
                if self._stop_event.is_set():
                    self._handle_stop_request(test)
                    break
                if self._soft_stop_event.is_set():
                    self._drain_queue()
                    break
                self._run_single_test(test)

        if self._soft_stop_event.is_set() and not self._stop_event.is_set():
            self._drain_queue()

    def stop(self):
        """Signal all work to stop as soon as possible."""
        self._stop_event.set()

    def soft_stop(self):
        """Signal the worker to finish its current test and stop picking up new ones."""
        self._soft_stop_event.set()

    def _drain_queue(self):
        """Drain remaining tests from the queue and mark them as STOPPED in the DB."""
        with PytestProcessInfoDB(self.data_dir) as db:
            while True:
                try:
                    scheduled_test = self.pytest_test_queue.get(False)
                except Empty:
                    break
                info = PytestProcessInfo(self.run_guid, scheduled_test.node_id, None, PyTestFlyExitCode.STOPPED, None, time_stamp=time.time())
                db.write(info)
