"""
Test-run orchestration — coordinates a pool of worker threads that execute
tests in parallel via :class:`PytestProcess` subprocesses.

:class:`PytestRunner` is the top-level thread; each worker is a
:class:`_TestRunner` thread that pulls from a shared queue.
:class:`PytestRunState` converts raw DB records into a display-friendly state.
"""

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from threading import Condition, Event, Lock, Thread
from typing import Optional

import psutil
from PySide6.QtGui import QColor
from typeguard import typechecked

from ..colors import BAR_COLORS, TABLE_COLORS
from ..db import PytestProcessInfoDB
from ..interfaces import PyTestFlyExitCode, PytestRunnerState, ScheduledTest
from ..logger import get_logger
from ..platform import get_performance_core_count
from .commit_memory import commit_charge_and_limit, subtree_process_count
from .const import TIMEOUT
from .process_monitor import normalize_cpu_percent
from .pytest_process import PytestProcess, PytestProcessInfo, reap_pids, terminate_process_tree

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


@dataclass(frozen=True)
class _AdmissionGateConfig:
    """Configuration for the dispatch-time admission gates (Part C).

    Both gates default to disabled, so dispatch behavior is unchanged until a gate is
    explicitly enabled. The gates only *defer* starting new tests; they never cap how
    long a running test may take.
    """

    process_count_gate_enabled: bool = False
    max_descendant_processes: int = 0  # ignored when the process-count gate is disabled
    commit_gate_enabled: bool = False
    commit_gate_threshold: float = 0.90  # fraction of the system commit limit


@dataclass(frozen=True)
class _StallConfig:
    """Configuration for the stall watchdog (Part B)."""

    enabled: bool = True
    warn_seconds: float = 600.0
    cpu_active_epsilon: float = 1.0
    auto_force_stop: bool = False
    kill_seconds: float = 1800.0


@dataclass(frozen=True)
class StallInfo:
    """Snapshot of the stall watchdog's view of the run (Part B). Read-only, GUI-facing."""

    stalled: bool
    stuck_tests: list[str] = field(default_factory=list)  # non-terminal test node-ids
    idle_pids: list[int] = field(default_factory=list)  # in-flight test PIDs sampled below cpu_active_epsilon
    descendant_count: int = 0  # processes in the controller's tree
    seconds_since_progress: float = 0.0  # wall time since the last DB state transition


_TERMINAL_STATES = frozenset({PytestRunnerState.PASS, PytestRunnerState.FAIL, PytestRunnerState.TERMINATED, PytestRunnerState.STOPPED})


def _latest_info_per_name(infos: list[PytestProcessInfo]) -> dict[str, PytestProcessInfo]:
    """Return the most recent :class:`PytestProcessInfo` per test name (by ``time_stamp``)."""
    latest: dict[str, PytestProcessInfo] = {}
    for info in infos:
        prior = latest.get(info.name)
        if prior is None or info.time_stamp >= prior.time_stamp:
            latest[info.name] = info
    return latest


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
        gate_config: _AdmissionGateConfig | None = None,
        stall_config: _StallConfig | None = None,
    ):
        self.run_guid = run_guid
        self.tests = tests
        self.number_of_processes = number_of_processes
        self.data_dir = data_dir
        self.update_rate = update_rate
        self.put_version = put_version
        self.put_fingerprint = put_fingerprint
        self.gate_config = gate_config or _AdmissionGateConfig()
        self.stall_config = stall_config or _StallConfig()
        self._controller_pid = os.getpid()

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
        self._watchdog: _StallWatchdog | None = None
        self._force_stopped = False  # one-way latch: user (or auto-escalation) force-stopped & reset

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

        # Part B: start the read-only stall watchdog once workers exist (so is_running()
        # is meaningful). It self-terminates when the run finishes.
        if self.stall_config.enabled and self._watchdog is None:
            self._watchdog = _StallWatchdog(
                self.run_guid,
                self.data_dir,
                self._controller_pid,
                self.stall_config,
                self.is_running,
                self.force_stop_and_reset,
                sample_interval=max(self.update_rate, 1.0),
            )
            self._watchdog.start()

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

    def get_run_completion(self) -> tuple[int, int, list[str]] | None:
        """Return ``(n_terminal, n_total, stuck)`` derived from the DB, or ``None`` on error (Part D).

        *terminal* means the test's latest record is PASS / FAIL / TERMINATED / STOPPED; a latest
        record of NONE (QUEUED or RUNNING) is non-terminal. This is the honest, DB-backed view of
        completion — unlike :meth:`is_running` (thread liveness), a wedged worker cannot make it
        report "still running" forever. Returns ``None`` on any DB error so callers fall back to
        :meth:`is_running`.
        """
        try:
            with PytestProcessInfoDB(self.data_dir) as db:
                infos = db.query(self.run_guid)
        except Exception as e:
            log.warning(f"get_run_completion DB read failed, falling back to is_running: {e}")
            return None
        latest = _latest_info_per_name(infos)
        if not latest:
            return 0, 0, []
        stuck = sorted(name for name, info in latest.items() if PytestRunState([info]).get_state() not in _TERMINAL_STATES)
        n_total = len(latest)
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
                latest = _latest_info_per_name(infos)
                for name, info in latest.items():
                    if PytestRunState([info]).get_state() in _TERMINAL_STATES:
                        continue
                    db.write(
                        PytestProcessInfo(
                            self.run_guid,
                            name,
                            None,
                            PyTestFlyExitCode.STOPPED,
                            None,
                            time_stamp=time.time(),
                            put_version=self.put_version,
                            put_fingerprint=self.put_fingerprint,
                        )
                    )
        except Exception as e:
            log.warning(f"force_stop_and_reset: error marking remaining tests STOPPED: {e}", exc_info=True)

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


class _StallWatchdog(Thread):
    """Read-only watchdog that flags a run as *stalled* (Part B).

    A run is stalled when, for at least ``warn_seconds``: a worker is alive and at least one
    test is non-terminal, **no** DB state transition has occurred, **and** no in-flight test's
    subtree CPU has exceeded ``cpu_active_epsilon``. This is a run-wide, activity-based signal —
    deliberately *not* a per-test clock: a long test that is actually burning CPU keeps resetting
    the timer and never flags, no matter how long it runs.

    The watchdog never terminates anything itself except the opt-in escalation
    (``auto_force_stop`` → ``escalate_fn`` after ``kill_seconds``); otherwise it only reads DB +
    psutil and publishes a :class:`StallInfo`, so it can never become a source of deadlock.

    The CPU sampler and progress source are injectable so tests can drive the watchdog with a
    fake clock and synthetic samples without depending on the host.
    """

    def __init__(
        self,
        run_guid: str,
        data_dir: Path,
        controller_pid: int | None,
        config: _StallConfig,
        is_running_fn,
        escalate_fn,
        sample_interval: float,
        clock=time.monotonic,
        cpu_sampler=None,
        progress_source=None,
    ) -> None:
        super().__init__(daemon=True)
        self.run_guid = run_guid
        self.data_dir = data_dir
        self.controller_pid = controller_pid
        self.config = config
        self._is_running_fn = is_running_fn
        self._escalate_fn = escalate_fn
        self._sample_interval = max(sample_interval, 0.1)
        self._clock = clock
        self._cpu_sampler = cpu_sampler or self._default_cpu_sampler
        self._progress_source = progress_source or self._default_progress_source

        self._stop_event = Event()
        self._state_lock = Lock()
        self._stall_info = StallInfo(stalled=False)

        self._cpu_procs: dict[int, psutil.Process] = {}  # persistent per-pid handle cache (roots + descendants) for interval=None subtree sampling
        self._last_fingerprint = None
        self._last_progress_monotonic = clock()
        self._escalated = False

    def stop(self) -> None:
        self._stop_event.set()

    def is_stalled(self) -> bool:
        with self._state_lock:
            return self._stall_info.stalled

    def get_stall_info(self) -> StallInfo | None:
        with self._state_lock:
            return self._stall_info

    def run(self) -> None:
        # Wait for at least one worker to exist so is_running() is meaningful, then tick until
        # the run finishes (all workers exited) or we are stopped.
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception as e:  # fail-open: never let a watchdog error stall or crash the run
                log.warning(f"stall watchdog tick error (logged once per tick): {e}")
                with self._state_lock:
                    self._stall_info = StallInfo(stalled=False)
            if not self._is_running_fn():
                break  # run finished — workers all drained
            self._stop_event.wait(self._sample_interval)

    def tick(self) -> None:
        """Evaluate the stall signal once and publish a fresh :class:`StallInfo`."""
        now = self._clock()
        fingerprint, stuck_tests, running_pids, _n_total = self._progress_source()

        live = self._is_running_fn() and len(stuck_tests) > 0
        if not live:
            self._last_progress_monotonic = now
            self._last_fingerprint = fingerprint
            self._publish(StallInfo(stalled=False))
            return

        # Progress: any DB state transition resets the no-progress timer.
        if fingerprint != self._last_fingerprint:
            self._last_fingerprint = fingerprint
            self._last_progress_monotonic = now

        # CPU activity: any in-flight test above epsilon resets the timer. Newly-seen pids are
        # primed (their first reading is meaningless) and treated as activity-unknown.
        idle_pids: list[int] = []
        any_active = False
        real_readings = 0
        for pid in running_pids:
            cpu = self._cpu_sampler(pid)
            if cpu is None:
                continue  # unknown (just primed or unreadable)
            real_readings += 1
            if cpu > self.config.cpu_active_epsilon:
                any_active = True
            else:
                idle_pids.append(pid)
        # Reset on real activity, or when we have running pids but no usable reading yet
        # (never fabricate a stall from a transient psutil error or an unprimed sampler).
        if any_active or (running_pids and real_readings == 0):
            self._last_progress_monotonic = now

        elapsed = now - self._last_progress_monotonic
        stalled = elapsed >= self.config.warn_seconds
        # Only walk the controller tree when we have something to report — avoids a recursive
        # process-tree walk on every healthy tick.
        descendant_count = subtree_process_count(self.controller_pid) if (stalled and self.controller_pid is not None) else 0
        info = StallInfo(stalled=stalled, stuck_tests=sorted(stuck_tests), idle_pids=idle_pids, descendant_count=descendant_count, seconds_since_progress=elapsed)
        self._publish(info)

        if stalled:
            log.warning(
                f"run appears stalled: {len(stuck_tests)} test(s) not progressing for {elapsed:.0f}s, "
                f"{len(idle_pids)} in-flight idle, {descendant_count} descendant process(es) ({self.run_guid=})"
            )
            self._maybe_escalate(elapsed)

    def _maybe_escalate(self, elapsed: float) -> None:
        cfg = self.config
        if not cfg.auto_force_stop or self._escalated:
            return
        if cfg.kill_seconds <= cfg.warn_seconds:
            log.warning("auto-force-stop enabled but the stall kill window is not greater than the stall warn window; escalation disabled")
            self._escalated = True  # log once
            return
        if elapsed >= cfg.kill_seconds:
            log.warning(f"auto-escalating: Force-stop & reset after {elapsed:.0f}s stall ({self.run_guid=})")
            self._escalated = True
            try:
                self._escalate_fn()
            except Exception as e:
                log.warning(f"error during auto Force-stop & reset: {e}", exc_info=True)

    def _publish(self, info: StallInfo) -> None:
        with self._state_lock:
            self._stall_info = info

    def _default_progress_source(self):
        """Read latest-per-name DB records → (fingerprint, stuck_tests, running_pids, n_total)."""
        with PytestProcessInfoDB(self.data_dir) as db:
            infos = db.query(self.run_guid)
        latest = _latest_info_per_name(infos)
        stuck: list[str] = []
        running_pids: list[int] = []
        n_terminal = 0
        n_running = 0
        max_started_ts = 0.0
        for name, info in latest.items():
            state = PytestRunState([info]).get_state()
            if state in _TERMINAL_STATES:
                n_terminal += 1
            else:
                stuck.append(name)
                if state == PytestRunnerState.RUNNING:
                    n_running += 1
                    if info.pid is not None:
                        running_pids.append(info.pid)
            if info.pid is not None:
                max_started_ts = max(max_started_ts, info.time_stamp)
        fingerprint = (n_terminal, n_running, max_started_ts)
        return fingerprint, stuck, running_pids, len(latest)

    def _default_cpu_sampler(self, pid: int) -> float | None:
        """Sample a pid's whole-subtree CPU percent (single-core-equiv), priming on first sight.

        psutil's ``cpu_percent(interval=None)`` returns usage as a delta against the *same* Process
        object's previous call, so every sampled process — the root **and each descendant** — needs
        a handle that persists across ticks (all cached in ``self._cpu_procs``). Re-creating child
        handles each tick would make them perpetually report the meaningless first-call ``0.0``,
        silently dropping the CPU of any subprocess/.exe a test spawns (so a test that offloads its
        work to a child would always read idle). Newly-seen descendants are primed here (they
        contribute ``0.0`` this tick, real readings thereafter); handles whose process has exited
        are dropped.
        """
        try:
            root = self._cpu_procs.get(pid)
            first_sight = root is None
            if root is None:
                root = psutil.Process(pid)
                self._cpu_procs[pid] = root
                root.cpu_percent(interval=None)  # prime; first reading is meaningless
            total = 0.0 if first_sight else root.cpu_percent(interval=None)
            for child in root.children(recursive=True):
                cached = self._cpu_procs.get(child.pid)
                try:
                    if cached is None:
                        # New descendant: cache + prime now so the next tick reads real usage.
                        self._cpu_procs[child.pid] = child
                        child.cpu_percent(interval=None)
                    else:
                        total += cached.cpu_percent(interval=None)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    self._cpu_procs.pop(child.pid, None)
            return None if first_sight else normalize_cpu_percent(total, get_performance_core_count())
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
            self._cpu_procs.pop(pid, None)
            return None


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

    def active_slot_count(self) -> int:
        """Return the number of in-flight slots (normal + singleton).

        ``0`` means nothing is currently running, which the admission gate uses for
        its min-1 forward-progress guarantee: a heavy test is always admitted when no
        other test is in flight, so the suite can never deadlock behind the gate.
        """
        with self._cond:
            return self._active


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
        controller_pid: int | None = None,
        gate_config: "_AdmissionGateConfig | None" = None,
    ) -> None:
        """
        :param run_guid: GUID identifying the overall test run.
        :param pytest_test_queue: Shared queue of :class:`ScheduledTest` to execute.
        :param data_dir: Directory used for the results database.
        :param update_rate: Polling / process-monitor sample interval in seconds.
        :param coordinator: Shared :class:`_SingletonCoordinator` that gates
            singleton vs. parallel execution across all workers.
        :param controller_pid: PID of the pytest-fly controller process, used by the
            process-count admission gate to measure the descendant tree.
        :param gate_config: Admission-gate configuration (Part C). ``None`` disables both gates.
        """
        super().__init__()

        self.run_guid = run_guid
        self.pytest_test_queue = pytest_test_queue
        self.data_dir = data_dir
        self.update_rate = update_rate
        self.put_version = put_version
        self.put_fingerprint = put_fingerprint
        self.controller_pid = controller_pid
        self.gate_config = gate_config or _AdmissionGateConfig()

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
        try:
            for child in psutil.Process(proc.pid).children(recursive=True):
                try:
                    snapshot.add((child.pid, child.create_time()))
                except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
                    continue
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
            pass

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
            if not self._await_admission(should_abort):
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

        if self._soft_stop_event.is_set() and not self._stop_event.is_set():
            self._drain_queue()

    def _handle_not_acquired(self, scheduled_test: ScheduledTest, test: str) -> None:
        """Dispose of a dequeued test when a slot could not be acquired or admission was aborted.

        Shared by the admission-gate-abort path and the coordinator-acquire-failure path:
        on stop, tree-kill the (not-yet-started) current process; on soft-stop, drain the
        remaining queue to STOPPED; on retire, hand the dequeued test back to a surviving worker.
        """
        if self._stop_event.is_set():
            self._handle_stop_request(test)
        elif self._soft_stop_event.is_set():
            self._drain_queue()
        elif self._retire_event.is_set():
            # Pool was shrunk while we waited. Hand the test we dequeued back so a
            # surviving worker runs it, then exit without draining — the remaining
            # queue belongs to the other workers.
            self.pytest_test_queue.put(scheduled_test)

    def _await_admission(self, should_abort) -> bool:
        """Defer dispatching the next test while an enabled admission gate is over budget (Part C).

        Composes the process-count and commit-charge gates as a logical AND. The min-1
        forward-progress guarantee (admit whenever nothing is in flight) overrides both, so a
        single heavy test can never deadlock the suite. Fail-open: a read error or a disabled
        gate admits. Poll-interruptible via *should_abort*.

        :return: ``True`` if admitted, ``False`` if *should_abort* went true while deferring.
        """
        cfg = self.gate_config
        if not (cfg.process_count_gate_enabled or cfg.commit_gate_enabled):
            return True
        while not should_abort():
            process_ok = not cfg.process_count_gate_enabled or self._process_count_ok()
            commit_ok = not cfg.commit_gate_enabled or self._commit_ok()
            if process_ok and commit_ok:
                return True
            if self._coordinator.active_slot_count() == 0:
                return True  # min-1: nothing in flight, always make forward progress
            self._stop_event.wait(self.update_rate)  # interruptible defer
        return False

    def _process_count_ok(self) -> bool:
        """Return ``True`` if the controller's descendant tree is below the ceiling (fail-open)."""
        if self.controller_pid is None:
            return True
        count = subtree_process_count(self.controller_pid)
        if count <= 0:  # fail-open: tree could not be read
            return True
        return count < self.gate_config.max_descendant_processes

    def _commit_ok(self) -> bool:
        """Return ``True`` if system commit charge is below the gate threshold (fail-open)."""
        commit = commit_charge_and_limit()
        if commit is None:
            return True  # signal unavailable -> admit
        commit_total, commit_limit = commit
        if commit_limit <= 0:
            return True
        return (commit_total / commit_limit) < self.gate_config.commit_gate_threshold

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
