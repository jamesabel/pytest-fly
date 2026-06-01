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
from threading import Condition, Event, Lock, Thread
from typing import Optional

from PySide6.QtGui import QColor
from typeguard import typechecked

from ..colors import BAR_COLORS, TABLE_COLORS
from ..db import PytestProcessInfoDB
from ..interfaces import PyTestFlyExitCode, PytestRunnerState, ScheduledTest
from ..logger import get_logger
from .const import TIMEOUT
from .pytest_process import PytestProcess, PytestProcessInfo, terminate_process_tree

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

        # Worker pool. _pool_lock guards _test_runners, _next_worker_id, and
        # number_of_processes so the pool can be resized from the GUI thread
        # (via set_number_of_processes) while run() spins it up on this thread.
        self._pool_lock = Lock()
        self._test_runners = {}
        self._next_worker_id = 0
        self._test_queue: Queue | None = None
        self._coordinator: _SingletonCoordinator | None = None
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

        # Publish the queue/coordinator and spawn the initial pool atomically so a
        # concurrent set_number_of_processes() either sees "not yet started" (and
        # just records the count for us to use here) or a fully-wired pool.
        with self._pool_lock:
            self._test_queue = test_queue
            self._coordinator = coordinator
            for _ in range(self.number_of_processes):
                self._spawn_worker_locked()
            self._started_event.set()

    def _spawn_worker_locked(self) -> None:
        """Start one worker thread pulling from the shared queue. Caller holds ``_pool_lock``."""
        test_runner = _TestRunner(
            self.run_guid,
            self._test_queue,
            self.data_dir,
            self.update_rate,
            self._coordinator,
            put_version=self.put_version,
            put_fingerprint=self.put_fingerprint,
        )
        test_runner.start()
        self._test_runners[self._next_worker_id] = test_runner
        self._next_worker_id += 1

    @typechecked()
    def set_number_of_processes(self, number_of_processes: int) -> None:
        """Resize the worker pool to *number_of_processes* while the run is in progress.

        Growing spawns additional workers that pull from the same shared queue;
        shrinking retires the most-recently-spawned workers — each finishes its
        current test, then exits *without* draining the queue, so its remaining
        tests stay available to the surviving workers.

        Reconciles against the count of live, non-retiring workers, so it is
        self-correcting and safe to call repeatedly.  If the pool has not been
        spun up yet, the new count is simply recorded and used by :meth:`run`.

        :param number_of_processes: Desired number of concurrently-working test processes (>= 1).
        """
        if number_of_processes < 1:
            return
        with self._pool_lock:
            self.number_of_processes = number_of_processes
            if not self._started_event.is_set():
                # run() has not spawned the pool yet; it will use the updated count.
                return
            # Drop workers that have already exited so the reconciliation below
            # counts only workers that can still pick up (or are running) tests.
            self._test_runners = {tid: r for tid, r in self._test_runners.items() if r.is_alive()}
            active = [r for r in self._test_runners.values() if not r.is_retiring()]
            delta = number_of_processes - len(active)
            if delta > 0:
                for _ in range(delta):
                    self._spawn_worker_locked()
            elif delta < 0:
                # Retire the most-recently-spawned workers (dict preserves insertion order).
                for test_runner in active[delta:]:
                    test_runner.retire()
            log.info(f"resized worker pool to {number_of_processes} ({len(active)} active before, delta {delta}) ({self.run_guid=})")

    def is_running(self) -> bool:
        """Return ``True`` if any worker thread is still alive."""
        with self._pool_lock:
            test_runners = list(self._test_runners.values())
        return any(test_runner.is_alive() for test_runner in test_runners)

    @typechecked()
    def join(self, timeout_seconds: float | None = None) -> bool:

        # in case join is called right after .start(), wait until .run() has started all workers
        if timeout_seconds is not None:
            start = time.time()
            while not self._started_event.is_set() and time.time() - start < timeout_seconds:
                time.sleep(0.1)
        else:
            self._started_event.wait()

        with self._pool_lock:
            test_runners = list(self._test_runners.values())
        for test_runner in test_runners:
            test_runner.join(timeout_seconds)
        return all(not test_runner.is_alive() for test_runner in test_runners)

    def stop(self):
        try:
            with self._pool_lock:
                test_runners = list(self._test_runners.values())
            for test_runner in test_runners:
                test_runner.stop()
        except (OSError, RuntimeError, PermissionError) as e:
            log.error(f"error stopping pytest runner,{self.run_guid=},{e}", exc_info=True, stack_info=True)

    def soft_stop(self):
        """Signal workers to finish their current test and stop picking up new ones."""
        try:
            with self._pool_lock:
                test_runners = list(self._test_runners.values())
            for test_runner in test_runners:
                test_runner.soft_stop()
        except (OSError, RuntimeError, PermissionError) as e:
            log.error(f"error soft-stopping pytest runner,{self.run_guid=},{e}", exc_info=True, stack_info=True)

    def force_stop_test(self, test_name: str) -> None:
        """Terminate a single running test identified by its node_id.

        Iterates worker threads and signals the one currently running the
        given test to terminate its process.  Other workers are unaffected.

        :param test_name: The test node_id to terminate.
        """
        with self._pool_lock:
            test_runners = list(self._test_runners.values())
        for test_runner in test_runners:
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
        self._retire_event = Event()
        self._force_stop_current_event = Event()

        self._coordinator = coordinator

    # ------------------------------------------------------------------
    # Process lifecycle helpers
    # ------------------------------------------------------------------

    def _terminate_process(self, proc: PytestProcess, proc_name: str, test: str) -> None:
        """
        Terminate *proc* and all of its descendants.  ``terminate_process_tree``
        handles SIGTERM-then-SIGKILL escalation internally and waits for the
        processes to exit, so this method records the ``TERMINATED`` status to
        the DB unconditionally.

        :param proc: The running :class:`PytestProcess`.
        :param proc_name: Human-readable name for log messages.
        :param test: Test node-ID (used when writing the DB record).
        """
        # reap_parent=False — we own the multiprocessing.Process lifecycle and
        # reap it ourselves via join() below. Letting psutil reap it would leave
        # the multiprocessing wrapper's is_alive() permanently True on POSIX.
        terminate_process_tree(proc.pid, terminate_timeout=max(self.update_rate, 2.0), reap_parent=False)
        proc.join(0.5)  # reap the multiprocessing.Process wrapper

        if proc.is_alive():
            log.warning(f'process for test "{proc_name}" still alive after tree kill ({self.run_guid=})')
        else:
            log.info(f'process tree for test "{proc_name}" terminated ({self.run_guid=})')

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
                    # terminate_process_tree already SIGKILL'd; don't loop and retry
                    break

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
            return self._stop_event.is_set() or self._soft_stop_event.is_set() or self._retire_event.is_set()

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
                if self._retire_event.is_set():
                    # Pool was shrunk while we waited for a slot. Hand the test we
                    # dequeued back so a surviving worker runs it, then exit without
                    # draining — the remaining queue belongs to the other workers.
                    self.pytest_test_queue.put(scheduled_test)
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

    def retire(self):
        """Signal the worker to finish its current test, then exit without draining the queue.

        Used to shrink the pool mid-run; unlike :meth:`soft_stop`, the remaining
        queued tests are left for the surviving workers rather than marked STOPPED.
        """
        self._retire_event.set()

    def is_retiring(self) -> bool:
        """Return ``True`` if this worker has been asked to retire."""
        return self._retire_event.is_set()

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
