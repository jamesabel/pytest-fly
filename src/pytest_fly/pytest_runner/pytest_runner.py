"""
Test-run orchestration — coordinates a pool of worker threads that execute
tests in parallel via :class:`PytestProcess` subprocesses.

:class:`PytestRunner` is the top-level thread; each worker is a
:class:`_TestRunner` thread that pulls from a shared queue.  Sibling modules hold the
supporting pieces: :mod:`.run_state` (DB record → display-state classification),
:mod:`.singleton_coordinator` (exclusive-test scheduling), and :mod:`.monitor_thread` /
:mod:`.resource_guard` (run-scoped monitor daemons).

"Part A/B/C/D" comments throughout refer to ``docs/pytest-fly-liveness-recovery-spec.md``:
Part A = orphaned-descendant reaping, Part B = the stall watchdog, Part C = the
admission gates, Part D = the DB-backed run-completion view.
"""

import os
import time
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Optional

from typeguard import typechecked

from ..db import PytestProcessInfoDB, PytestProcessInfoReader
from ..interfaces import PyTestFlyExitCode, ScheduledTest, status_record
from ..logger import EVENT_EXTRA, get_logger
from .admission import AdmissionGate, AdmissionGateConfig
from .commit_memory import PSUTIL_READ_ERRORS, subtree_processes
from .const import FAIL_OPEN_ERRORS, TIMEOUT
from .pytest_process import PytestProcess, reap_pids, terminate_process_tree
from .resource_guard import ResourceGuard, ResourceGuardConfig, ResourceGuardInfo
from .run_state import TERMINAL_STATES, latest_info_per_name, latest_states
from .run_state import PytestRunState as PytestRunState  # re-export: lived here before the run_state extraction
from .singleton_coordinator import SingletonCoordinator
from .stall_watchdog import StallConfig, StallInfo, StallWatchdog

log = get_logger()

# Backward-compatible aliases for names that predate the run_state / singleton_coordinator /
# stall_watchdog / admission extractions (still imported from this module by older call
# sites and tests).
_TERMINAL_STATES = TERMINAL_STATES
_latest_info_per_name = latest_info_per_name
_SingletonCoordinator = SingletonCoordinator
_AdmissionGateConfig = AdmissionGateConfig
_StallConfig = StallConfig
_StallWatchdog = StallWatchdog


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
        gate_config: AdmissionGateConfig | None = None,
        stall_config: StallConfig | None = None,
        resource_guard_config: ResourceGuardConfig | None = None,
    ):
        self.run_guid = run_guid
        self.tests = tests
        self.number_of_processes = number_of_processes
        self.data_dir = data_dir
        self.update_rate = update_rate
        self.put_version = put_version
        self.put_fingerprint = put_fingerprint
        self.gate_config = gate_config or AdmissionGateConfig()
        self.stall_config = stall_config or StallConfig()
        self.resource_guard_config = resource_guard_config or ResourceGuardConfig()
        self._controller_pid = os.getpid()

        # Worker pool. _pool_lock guards _test_runners, _next_worker_id, and
        # number_of_processes so the pool can be resized from the GUI thread
        # (via set_number_of_processes) while run() spins it up on this thread.
        self._pool_lock = Lock()
        self._test_runners = {}
        self._next_worker_id = 0
        self._test_queue: Queue | None = None
        self._coordinator: SingletonCoordinator | None = None
        self._started_event = Event()
        self._watchdog: StallWatchdog | None = None
        self._resource_guard: ResourceGuard | None = None
        self._force_stopped = False  # one-way latch: user (or auto-escalation) force-stopped & reset
        self._stop_requested = False  # hard stop requested; suppresses pool healing and soft-stop cancel
        # Runner-owned so a pending soft stop can be canceled: workers share this single
        # event, and the queue is only drained to STOPPED at run finalization (see run()),
        # not by the first idle worker — that's what keeps the queued tests recoverable.
        self._soft_stop_event = Event()
        self._queue_finalized = False  # one-way latch: the run wound down; a soft stop can no longer be canceled

        super().__init__()

    def run(self):
        """Run the whole test-run lifecycle on this thread.

        Enqueues every test (writing its QUEUED record), spins up the worker pool and the
        optional monitor daemons (stall watchdog, resource guard), then supervises the pool
        until the run winds down — topping workers back up after a canceled soft stop or an
        unexpected worker death, and finalizing a soft stop by marking the still-queued
        tests STOPPED once every worker has exited.
        """

        test_queue = Queue()
        with PytestProcessInfoDB(self.data_dir) as db:
            for test in self.tests:
                test_queue.put(test)
                db.write(status_record(self.run_guid, test.node_id, PyTestFlyExitCode.NONE, self.put_version, self.put_fingerprint))  # queued

        coordinator = SingletonCoordinator()

        # Publish the queue/coordinator and spawn the initial pool atomically so a
        # concurrent set_number_of_processes() either sees "not yet started" (and
        # just records the count for us to use here) or a fully-wired pool.
        with self._pool_lock:
            self._test_queue = test_queue
            self._coordinator = coordinator
            for _ in range(self.number_of_processes):
                self._spawn_worker_locked()
            self._started_event.set()

        # Part B: start the read-only stall watchdog once workers exist (so is_running()
        # is meaningful). It self-terminates when the run finishes.
        if self.stall_config.enabled and self._watchdog is None:
            self._watchdog = StallWatchdog(
                self.run_guid,
                self.data_dir,
                self._controller_pid,
                self.stall_config,
                self.is_running,
                self.force_stop_and_reset,
                sample_interval=max(self.update_rate, 1.0),
            )
            self._watchdog.start()

        # Resource guard: opt-in background monitor that soft-stops the run when the system
        # is low on disk or commit space. Like the watchdog, it self-terminates when the run
        # finishes. The soft stop it requests is the ordinary cancelable one, so the user can
        # override it with Cancel Stop.
        if self.resource_guard_config.enabled and self._resource_guard is None:
            self._resource_guard = ResourceGuard(
                self.run_guid,
                self.data_dir,
                self.resource_guard_config,
                self.is_running,
                self.soft_stop,
                sample_interval=max(self.update_rate, 1.0),
            )
            self._resource_guard.start()

        # Supervise the pool until the run winds down. This loop is what makes a soft
        # stop cancelable: workers no longer drain the queue themselves — they simply
        # exit — so queued tests stay schedulable until every worker has finished, and
        # only then are they marked STOPPED (the point of no return). The loop also tops
        # the pool back up if a worker exited on a soft stop that was later canceled
        # (covers the window where cancel_soft_stop's respawn undercounts a worker that
        # was still mid-exit) or died unexpectedly while tests remain queued.
        while True:
            with self._pool_lock:
                self._test_runners = {tid: r for tid, r in self._test_runners.items() if r.is_alive()}
                if not self._test_runners:
                    if self._soft_stop_event.is_set() and not self._force_stopped:
                        self._mark_queued_tests_stopped()
                    self._queue_finalized = True
                    break
                if not (self._soft_stop_event.is_set() or self._stop_requested) and not self._test_queue.empty():
                    active = [r for r in self._test_runners.values() if not r.is_retiring()]
                    for _ in range(self.number_of_processes - len(active)):
                        self._spawn_worker_locked()
            time.sleep(min(self.update_rate, 1.0))

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
            controller_pid=self._controller_pid,
            gate_config=self.gate_config,
            soft_stop_event=self._soft_stop_event,
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
            log.info(f"resized worker pool to {number_of_processes} ({len(active)} active before, delta {delta}) ({self.run_guid=})", extra=EVENT_EXTRA)

    def is_running(self) -> bool:
        """Return ``True`` if any worker thread is still alive."""
        with self._pool_lock:
            test_runners = list(self._test_runners.values())
        return any(test_runner.is_alive() for test_runner in test_runners)

    def get_run_completion(self) -> tuple[int, int, list[str]] | None:
        """Return ``(n_terminal, n_total, stuck)`` derived from the DB, or ``None`` on error (Part D).

        *terminal* means the test's latest record is PASS / FAIL / TERMINATED / STOPPED; a latest
        record of NONE (QUEUED or RUNNING) is non-terminal. This is the honest, DB-backed view of
        completion — unlike :meth:`is_running` (thread liveness), a wedged worker cannot make it
        report "still running" forever. Returns ``None`` on any DB error so callers fall back to
        :meth:`is_running`.
        """
        try:
            # Read-only snapshot — callers include the GUI thread, which must never
            # contend for the DB's exclusive write lock.
            with PytestProcessInfoReader(self.data_dir) as db:
                infos = db.query(self.run_guid)
        except FAIL_OPEN_ERRORS as e:
            log.warning(f"get_run_completion DB read failed, falling back to is_running: {e}")
            return None
        states = latest_states(infos)
        if not states:
            return 0, 0, []
        stuck = sorted(name for name, state in states.items() if state not in TERMINAL_STATES)
        n_total = len(states)
        n_terminal = n_total - len(stuck)
        return n_terminal, n_total, stuck

    def is_user_complete(self) -> bool:
        """Return ``True`` if the run is finished from the *user's* perspective (Part D).

        True when the user/auto force-stopped, or every test reached a terminal state. Falls back
        to ``not is_running()`` if the completion view is unavailable. Drives Run-button
        enablement so a wedged worker thread can never permanently disable Run.
        """
        if self._force_stopped:
            return True
        completion = self.get_run_completion()
        if completion is None:
            return not self.is_running()
        n_terminal, n_total, _stuck = completion
        return n_total > 0 and n_terminal == n_total

    def was_force_stopped(self) -> bool:
        """Return ``True`` if this run was force-stopped & reset."""
        return self._force_stopped

    def get_stall_info(self) -> StallInfo | None:
        """Return the latest :class:`StallInfo` from the watchdog, or ``None`` if not running (Part B)."""
        watchdog = self._watchdog
        if watchdog is None:
            return None
        return watchdog.get_stall_info()

    def get_resource_guard_info(self) -> ResourceGuardInfo | None:
        """Return the latest :class:`ResourceGuardInfo`, or ``None`` when the guard is not enabled."""
        resource_guard = self._resource_guard
        if resource_guard is None:
            return None
        return resource_guard.get_info()

    def is_soft_stop_pending(self) -> bool:
        """Return ``True`` while a soft stop (user- or resource-guard-requested) is pending.

        Lets the GUI reflect a soft stop it did not itself initiate (the resource guard's
        automatic stop) — e.g. relabeling the Stop button to Cancel Stop.
        """
        return self._soft_stop_event.is_set()

    def force_stop_and_reset(self) -> None:
        """Force-stop every worker and mark all non-terminal tests STOPPED so the run completes (Part D).

        Recovery for a wedged run: :meth:`stop` tree-kills in-flight processes, which unblocks each
        wedged poll loop (``is_alive()`` flips False) and each ``acquire_singleton`` waiter (the stop
        predicate fires), so all worker threads drain naturally. Remaining non-terminal tests
        (the just-killed wedged test plus singletons blocked behind it) are written STOPPED so the
        table is internally consistent. Idempotent.
        """
        self._force_stopped = True
        self.stop()
        try:
            with PytestProcessInfoDB(self.data_dir) as db:
                infos = db.query(self.run_guid)
                for name, state in latest_states(infos).items():
                    if state in TERMINAL_STATES:
                        continue
                    db.write(status_record(self.run_guid, name, PyTestFlyExitCode.STOPPED, self.put_version, self.put_fingerprint))
        except FAIL_OPEN_ERRORS as e:
            log.warning(f"force_stop_and_reset: error marking remaining tests STOPPED: {e}", exc_info=True)

    @typechecked()
    def join(self, timeout_seconds: float | None = None) -> bool:
        """Wait for the run to finish: every worker thread, then the runner thread itself.

        Unlike :meth:`Thread.join` this returns a bool — ``True`` when everything exited
        within the timeout. Waits for the pool to be spun up first, so calling right after
        :meth:`start` is safe.

        :param timeout_seconds: Per-thread join timeout, or ``None`` to wait indefinitely.
        :return: ``True`` if all workers and the runner thread have exited.
        """

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
        # Also join the runner thread itself so soft-stop finalization (marking the
        # remaining queue STOPPED) is complete when join() returns.
        Thread.join(self, timeout_seconds)
        return all(not test_runner.is_alive() for test_runner in test_runners) and not self.is_alive()

    def stop(self):
        """Hard stop: signal every worker to terminate its current test as soon as possible.

        Not cancelable (unlike :meth:`soft_stop`) — it suppresses pool healing and the
        soft-stop cancel path, and tree-kills in-flight test processes. Also shuts down
        the monitor daemons promptly instead of waiting for their next sample interval.
        """
        self._stop_requested = True
        for monitor in (self._watchdog, self._resource_guard):
            if monitor is not None:
                monitor.stop()
        try:
            with self._pool_lock:
                test_runners = list(self._test_runners.values())
            for test_runner in test_runners:
                test_runner.stop()
        except (OSError, RuntimeError, PermissionError) as e:
            log.error(f"error stopping pytest runner,{self.run_guid=},{e}", exc_info=True, stack_info=True)

    def soft_stop(self):
        """Signal workers to finish their current test and stop picking up new ones.

        Cancelable via :meth:`cancel_soft_stop` until the run winds down (every worker
        has exited and the still-queued tests have been marked STOPPED).
        """
        self._soft_stop_event.set()

    def cancel_soft_stop(self) -> bool:
        """Cancel a pending soft stop so the still-queued tests keep running.

        Possible until the run finalizes — all workers exited and the remaining queue was
        drained to STOPPED. Workers that already exited on the soft stop are respawned so
        the pool returns to its configured size (the supervision loop in :meth:`run` heals
        any respawn shortfall from a worker caught mid-exit).

        :return: ``True`` if the soft stop was canceled (or none was pending), ``False`` if it was too late.
        """
        with self._pool_lock:
            if self._queue_finalized or self._force_stopped or self._stop_requested:
                return False
            if not self._soft_stop_event.is_set():
                return True  # nothing pending
            self._soft_stop_event.clear()
            if self._started_event.is_set():
                self._test_runners = {tid: r for tid, r in self._test_runners.items() if r.is_alive()}
                active = [r for r in self._test_runners.values() if not r.is_retiring()]
                for _ in range(self.number_of_processes - len(active)):
                    self._spawn_worker_locked()
            log.info(f"soft stop canceled ({self.run_guid=})", extra=EVENT_EXTRA)
        return True

    def _mark_queued_tests_stopped(self) -> None:
        """Drain the remaining queue and mark those tests STOPPED in the DB (soft-stop finalization)."""
        test_queue = self._test_queue
        if test_queue is None:  # run() has not published the queue yet; nothing to drain
            return
        with PytestProcessInfoDB(self.data_dir) as db:
            while True:
                try:
                    scheduled_test = test_queue.get(False)
                except Empty:
                    break
                db.write(status_record(self.run_guid, scheduled_test.node_id, PyTestFlyExitCode.STOPPED, self.put_version, self.put_fingerprint))

    def force_stop_test(self, test_name: str) -> bool:
        """Terminate a single running test identified by its node_id.

        Iterates worker threads and signals the one currently running the
        given test to terminate its process.  Other workers are unaffected.

        :param test_name: The test node_id to terminate.
        :return: ``True`` if a worker was signaled, ``False`` if no worker is currently
            running the test (e.g. a stale "Running" row whose process is already gone —
            the caller is expected to clear it in the DB).
        """
        with self._pool_lock:
            test_runners = list(self._test_runners.values())
        for test_runner in test_runners:
            proc = test_runner.process
            if proc is not None and proc.name == test_name:
                test_runner.force_stop_current()
                log.info(f'force stop requested for test "{test_name}" ({self.run_guid=})', extra=EVENT_EXTRA)
                return True
        log.warning(f'force stop: no running process found for test "{test_name}" ({self.run_guid=})')
        return False


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
        coordinator: SingletonCoordinator,
        put_version: str = "",
        put_fingerprint: str = "",
        controller_pid: int | None = None,
        gate_config: "AdmissionGateConfig | None" = None,
        soft_stop_event: Event | None = None,
    ) -> None:
        """
        :param run_guid: GUID identifying the overall test run.
        :param pytest_test_queue: Shared queue of :class:`ScheduledTest` to execute.
        :param data_dir: Directory used for the results database.
        :param update_rate: Polling / process-monitor sample interval in seconds.
        :param coordinator: Shared :class:`SingletonCoordinator` that gates
            singleton vs. parallel execution across all workers.
        :param controller_pid: PID of the pytest-fly controller process, used by the
            process-count admission gate to measure the descendant tree.
        :param gate_config: Admission-gate configuration (Part C). ``None`` disables both gates.
        :param soft_stop_event: Runner-owned soft-stop event shared by all workers, so a
            pending soft stop can be canceled centrally. ``None`` creates a private one.
        """
        super().__init__()

        self.run_guid = run_guid
        self.pytest_test_queue = pytest_test_queue
        self.data_dir = data_dir
        self.update_rate = update_rate
        self.put_version = put_version
        self.put_fingerprint = put_fingerprint
        self.controller_pid = controller_pid
        self.gate_config = gate_config or AdmissionGateConfig()
        self._admission_gate = AdmissionGate(self.gate_config, controller_pid)

        self.process: Optional[PytestProcess] = None
        self._stop_event = Event()
        self._soft_stop_event = soft_stop_event if soft_stop_event is not None else Event()
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
            db.write(status_record(self.run_guid, test, PyTestFlyExitCode.TERMINATED, self.put_version, self.put_fingerprint))

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

        # Rolling snapshot of the test's descendant tree as {(pid, create_time)}.
        # Captured while the test is still alive because once PytestProcess exits
        # its children can no longer be enumerated from the (dead) parent. Reaped
        # on the normal-exit path so a finished test leaves no orphans (Part A).
        descendant_snapshot: set[tuple[int, float]] = set()
        try:
            self.process = PytestProcess(self.run_guid, test, self.data_dir, self.update_rate, self.put_version, self.put_fingerprint)
            log.info(f'Starting process for test "{test}" ({self.run_guid=})')
            self.process.start()

            while self.process.is_alive():
                if self._stop_event.is_set() or self._force_stop_current_event.is_set():
                    self._handle_stop_request(test)
                    # terminate_process_tree already SIGKILL'd; don't loop and retry
                    break

                self._refresh_descendant_snapshot(descendant_snapshot)
                self.process.join(self.update_rate)

            self.process.join(TIMEOUT)  # should already be done, but just in case
            if self.process.is_alive():
                log.warning(f'process for test "{self.process.name}" did not terminate ({self.run_guid=})')
            else:
                log.info(f'process for test "{self.process.name}" completed ({self.run_guid=})')
        finally:
            # Part A: reap any descendants left behind by a test that finished on its
            # own. Skip the stop branch — _terminate_process already tree-killed there —
            # and only reap once the parent is confirmed dead (so survivors are
            # unambiguous orphans, not a still-running test). Fail-open inside reap_pids.
            stopped = self._stop_event.is_set() or self._force_stop_current_event.is_set()
            if not stopped and self.process is not None and not self.process.is_alive():
                reap_pids(descendant_snapshot)
            self._force_stop_current_event.clear()

    def _refresh_descendant_snapshot(self, snapshot: set[tuple[int, float]]) -> None:
        """Union the test process's current descendants into *snapshot* as ``(pid, create_time)``.

        Accumulates rather than replaces: a child that dies before the next poll would
        otherwise be missed, and the ``create_time`` match in :func:`reap_pids` discards
        dead or recycled entries at reap time. Fail-open — any psutil error is ignored.
        """
        proc = self.process
        if proc is None or proc.pid is None:
            return
        for child in subtree_processes(proc.pid)[1:]:  # [0] is the test process itself
            try:
                snapshot.add((child.pid, child.create_time()))
            except PSUTIL_READ_ERRORS:
                continue

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

            # Part C: throttle BEFORE acquiring a coordinator slot. A worker that has
            # dequeued but not yet acquired holds nothing, so deferring here can never
            # starve a singleton or deadlock when every worker is waiting.
            if not self._await_admission(should_abort, test):
                self._handle_not_acquired(scheduled_test, test)
                break

            if is_singleton:
                acquired = self._coordinator.acquire_singleton(should_abort, self.update_rate)
            else:
                acquired = self._coordinator.acquire_normal(should_abort, self.update_rate)

            if not acquired:
                self._handle_not_acquired(scheduled_test, test)
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

        # On soft stop the worker just exits — it does NOT drain the queue. The queued
        # tests stay schedulable so the soft stop can be canceled; if it isn't, the
        # runner marks them STOPPED once every worker has exited (soft-stop finalization).

    def _handle_not_acquired(self, scheduled_test: ScheduledTest, test: str) -> None:
        """Dispose of a dequeued test when a slot could not be acquired or admission was aborted.

        Shared by the admission-gate-abort path and the coordinator-acquire-failure path:
        on stop, tree-kill the (not-yet-started) current process; on soft-stop or retire,
        hand the dequeued test back — on retire a surviving worker runs it, on soft-stop
        it is either resumed (stop canceled) or marked STOPPED at finalization.
        """
        if self._stop_event.is_set():
            self._handle_stop_request(test)
        elif self._soft_stop_event.is_set() or self._retire_event.is_set():
            self.pytest_test_queue.put(scheduled_test)

    def _await_admission(self, should_abort, test: str = "") -> bool:
        """Defer dispatching the next test while an enabled admission gate is at capacity (Part C).

        The per-gate checks (AND-composed, fail-open) live in :class:`AdmissionGate`; this
        loop owns the timing: the min-1 forward-progress guarantee (admit whenever nothing
        is in flight) overrides the gates so a single heavy test can never deadlock the
        suite, and the defer is poll-interruptible via *should_abort*.

        Each defer episode is logged once at its start (with the at-capacity gates), and
        once at its end (admitted, min-1 override, or aborted).

        :param should_abort: Predicate polled between gate checks; ``True`` ends the defer.
        :param test: Test node id being dispatched — log context only.
        :return: ``True`` if admitted, ``False`` if *should_abort* went true while deferring.
        """
        gate = self._admission_gate
        if not gate.any_enabled():
            return True
        defer_start = None
        while not should_abort():
            failing = gate.failing_gates()
            if not failing:
                if defer_start is not None:
                    log.info(f'admission gate: admitted "{test}" after deferring {time.monotonic() - defer_start:.0f}s', extra=EVENT_EXTRA)
                return True
            if self._coordinator.active_slot_count() == 0:
                # min-1: nothing in flight, always make forward progress
                log.info(f'admission gate: at capacity ({", ".join(failing)}) but nothing in flight — admitting "{test}" for forward progress', extra=EVENT_EXTRA)
                return True
            if defer_start is None:
                defer_start = time.monotonic()
                log.info(f'admission gate: deferring dispatch of "{test}" — at capacity: {", ".join(failing)}', extra=EVENT_EXTRA)
            self._stop_event.wait(self.update_rate)  # interruptible defer
        if defer_start is not None:
            log.info(f'admission gate: defer of "{test}" ended by stop/soft-stop/retire after {time.monotonic() - defer_start:.0f}s', extra=EVENT_EXTRA)
        return False

    def stop(self):
        """Signal all work to stop as soon as possible."""
        self._stop_event.set()

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
