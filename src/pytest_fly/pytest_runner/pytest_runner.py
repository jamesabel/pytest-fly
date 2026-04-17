"""
Test-run orchestration — coordinates a pool of worker threads that execute
tests in parallel via :class:`PytestProcess` subprocesses.

:class:`PytestRunner` is the top-level thread; each worker is a
:class:`_TestRunner` thread that pulls from a shared queue.
:class:`PytestRunState` converts raw DB records into a display-friendly state.
"""

import time
from pathlib import Path
from queue import Empty, Queue
from threading import Condition, Event, Thread
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
    def __init__(
        self,
        run_guid: str,
        tests: list[ScheduledTest],
        number_of_processes: int,
        data_dir: Path,
        update_rate: float,
        put_version: str = "",
        put_fingerprint: str = "",
    ):
        self.run_guid = run_guid
        self.tests = tests
        self.number_of_processes = number_of_processes
        self.data_dir = data_dir
        self.update_rate = update_rate
        self.put_version = put_version
        self.put_fingerprint = put_fingerprint

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
                pytest_process_info = PytestProcessInfo(
                    self.run_guid,
                    test.node_id,
                    None,
                    PyTestFlyExitCode.NONE,
                    None,
                    time_stamp=time.time(),
                    put_version=self.put_version,
                    put_fingerprint=self.put_fingerprint,
                )  # queued
                db.write(pytest_process_info)

        coordinator = _SingletonCoordinator()

        for thread_number in range(self.number_of_processes):
            test_runner = _TestRunner(
                self.run_guid,
                test_queue,
                self.data_dir,
                self.update_rate,
                coordinator,
                put_version=self.put_version,
                put_fingerprint=self.put_fingerprint,
            )
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

    def force_stop_test(self, test_name: str) -> None:
        """Terminate a single running test identified by its node_id.

        Iterates worker threads and signals the one currently running the
        given test to terminate its process.  Other workers are unaffected.

        :param test_name: The test node_id to terminate.
        """
        for test_runner in self._test_runners.values():
            proc = test_runner.process
            if proc is not None and proc.name == test_name:
                test_runner.force_stop_current()
                log.info(f'force stop requested for test "{test_name}" ({self.run_guid=})')
                return
        log.warning(f'force stop: no running process found for test "{test_name}" ({self.run_guid=})')


class _SingletonCoordinator:
    """
    Serializes singleton tests against all other worker threads.

    A *singleton* must run exclusively — no other workers executing.  A
    *normal* test may run in parallel with any number of other normal tests.

    The slot counter and exclusion flag live under a single
    :class:`threading.Condition` so check-and-claim is atomic.  Waiting
    singletons block new normal acquisitions, preventing starvation.

    Acquires are poll-interruptible via *stop_predicate* so a worker can
    abandon its wait when a stop has been requested.
    """

    def __init__(self) -> None:
        self._cond = Condition()
        self._active = 0
        self._singleton_running = False
        self._singleton_waiters = 0

    def acquire_normal(self, stop_predicate, poll_interval: float) -> bool:
        """Claim a non-exclusive slot.  Returns ``False`` if *stop_predicate* went true while waiting."""
        with self._cond:
            while self._singleton_running or self._singleton_waiters > 0:
                if stop_predicate():
                    return False
                self._cond.wait(timeout=poll_interval)
            self._active += 1
            return True

    def release_normal(self) -> None:
        with self._cond:
            self._active -= 1
            self._cond.notify_all()

    def acquire_singleton(self, stop_predicate, poll_interval: float) -> bool:
        """Claim exclusive access.  Returns ``False`` if *stop_predicate* went true while waiting."""
        with self._cond:
            self._singleton_waiters += 1
            try:
                while self._singleton_running or self._active > 0:
                    if stop_predicate():
                        return False
                    self._cond.wait(timeout=poll_interval)
                self._singleton_running = True
                self._active += 1
                return True
            finally:
                self._singleton_waiters -= 1
                if self._singleton_waiters == 0:
                    self._cond.notify_all()

    def release_singleton(self) -> None:
        with self._cond:
            self._singleton_running = False
            self._active -= 1
            self._cond.notify_all()


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
        coordinator: _SingletonCoordinator,
        put_version: str = "",
        put_fingerprint: str = "",
    ) -> None:
        """
        :param run_guid: GUID identifying the overall test run.
        :param pytest_test_queue: Shared queue of :class:`ScheduledTest` to execute.
        :param data_dir: Directory used for the results database.
        :param update_rate: Polling / process-monitor sample interval in seconds.
        :param coordinator: Shared :class:`_SingletonCoordinator` that gates
            singleton vs. parallel execution across all workers.
        """
        super().__init__()

        self.run_guid = run_guid
        self.pytest_test_queue = pytest_test_queue
        self.data_dir = data_dir
        self.update_rate = update_rate
        self.put_version = put_version
        self.put_fingerprint = put_fingerprint

        self.process: Optional[PytestProcess] = None
        self._stop_event = Event()
        self._soft_stop_event = Event()
        self._force_stop_current_event = Event()

        self._coordinator = coordinator

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
                info = PytestProcessInfo(
                    self.run_guid,
                    test,
                    None,
                    PyTestFlyExitCode.TERMINATED,
                    None,
                    time_stamp=time.time(),
                    put_version=self.put_version,
                    put_fingerprint=self.put_fingerprint,
                )
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
        """Run a single test process.  Caller owns the coordinator slot."""

        try:
            self.process = PytestProcess(self.run_guid, test, self.data_dir, self.update_rate, self.put_version, self.put_fingerprint)
            log.info(f'Starting process for test "{test}" ({self.run_guid=})')
            self.process.start()

            while self.process.is_alive():
                if self._stop_event.is_set() or self._force_stop_current_event.is_set():
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
            self._force_stop_current_event.clear()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self):
        """Consume tests from the queue until it is empty or a stop is requested."""

        def should_abort() -> bool:
            return self._stop_event.is_set() or self._soft_stop_event.is_set()

        while not should_abort():
            try:
                scheduled_test = self.pytest_test_queue.get(False)
            except Empty:
                break

            test = scheduled_test.node_id
            is_singleton = scheduled_test.singleton

            if is_singleton:
                acquired = self._coordinator.acquire_singleton(should_abort, self.update_rate)
            else:
                acquired = self._coordinator.acquire_normal(should_abort, self.update_rate)

            if not acquired:
                if self._stop_event.is_set():
                    self._handle_stop_request(test)
                    break
                if self._soft_stop_event.is_set():
                    self._drain_queue()
                    break
                break

            try:
                if is_singleton:
                    log.info(f'Running singleton test "{test}" ({self.run_guid=})')
                self._run_single_test(test)
            finally:
                if is_singleton:
                    self._coordinator.release_singleton()
                else:
                    self._coordinator.release_normal()

        if self._soft_stop_event.is_set() and not self._stop_event.is_set():
            self._drain_queue()

    def stop(self):
        """Signal all work to stop as soon as possible."""
        self._stop_event.set()

    def soft_stop(self):
        """Signal the worker to finish its current test and stop picking up new ones."""
        self._soft_stop_event.set()

    def force_stop_current(self):
        """Signal this worker to terminate its currently running test."""
        self._force_stop_current_event.set()

    def _drain_queue(self):
        """Drain remaining tests from the queue and mark them as STOPPED in the DB."""
        with PytestProcessInfoDB(self.data_dir) as db:
            while True:
                try:
                    scheduled_test = self.pytest_test_queue.get(False)
                except Empty:
                    break
                info = PytestProcessInfo(
                    self.run_guid,
                    scheduled_test.node_id,
                    None,
                    PyTestFlyExitCode.STOPPED,
                    None,
                    time_stamp=time.time(),
                    put_version=self.put_version,
                    put_fingerprint=self.put_fingerprint,
                )
                db.write(info)
