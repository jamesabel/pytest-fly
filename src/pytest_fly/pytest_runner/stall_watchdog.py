"""
Stall watchdog — detects a wedged run (Part B of ``docs/pytest-fly-liveness-recovery-spec.md``).

A run is *stalled* when, for a configurable window, no test starts or finishes **and** no
in-flight test's process subtree uses any CPU.  The watchdog is read-only (DB + psutil)
and advisory — it publishes a :class:`StallInfo` for the GUI banner and never terminates
anything itself, except the opt-in automatic escalation.
"""

import time
from dataclasses import dataclass, field
from pathlib import Path

from ..db import PytestProcessInfoDB
from ..interfaces import PytestRunnerState
from ..logger import get_logger
from ..platform import get_performance_core_count
from .commit_memory import subtree_process_count
from .const import FAIL_OPEN_ERRORS
from .monitor_thread import MonitorThread
from .process_monitor import SubtreeCpuSampler, normalize_cpu_percent
from .run_state import TERMINAL_STATES, latest_info_per_name, state_of

log = get_logger()


@dataclass(frozen=True)
class StallConfig:
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


class StallWatchdog(MonitorThread):
    """Read-only watchdog that flags a run as *stalled* (Part B).

    A run is stalled when, for at least ``warn_seconds``: a worker is alive and at least one
    test is non-terminal, **no** DB state transition has occurred, **and** no in-flight test's
    subtree CPU has exceeded ``cpu_active_epsilon``. This is a run-wide, activity-based signal —
    deliberately *not* a per-test clock: a long test that is actually burning CPU keeps resetting
    the timer and never flags, no matter how long it runs.

    The watchdog never terminates anything itself except the opt-in escalation
    (``auto_force_stop`` → ``escalate_fn`` after ``kill_seconds``); otherwise it only reads DB +
    psutil and publishes a :class:`StallInfo`, so it can never become a source of deadlock.
    The tick loop, stop signal, and fail-open error policy come from :class:`MonitorThread`.

    The CPU sampler and progress source are injectable so tests can drive the watchdog with a
    fake clock and synthetic samples without depending on the host.
    """

    def __init__(
        self,
        run_guid: str,
        data_dir: Path,
        controller_pid: int | None,
        config: StallConfig,
        is_running_fn,
        escalate_fn,
        sample_interval: float,
        clock=time.monotonic,
        cpu_sampler=None,
        progress_source=None,
    ) -> None:
        super().__init__(is_running_fn, sample_interval)
        self.run_guid = run_guid
        self.data_dir = data_dir
        self.controller_pid = controller_pid
        self.config = config
        self._escalate_fn = escalate_fn
        self._clock = clock
        self._cpu_sampler = cpu_sampler or self._default_cpu_sampler
        self._progress_source = progress_source or self._default_progress_source

        self._stall_info = StallInfo(stalled=False)
        self._subtree_cpu = SubtreeCpuSampler()  # persistent-handle cache for interval=None subtree sampling
        self._last_fingerprint = None
        self._last_progress_monotonic = clock()
        self._escalated = False

    def is_stalled(self) -> bool:
        """Return ``True`` if the most recent tick classified the run as stalled."""
        with self._state_lock:
            return self._stall_info.stalled

    def get_stall_info(self) -> StallInfo | None:
        """Return the most recently published :class:`StallInfo`."""
        with self._state_lock:
            return self._stall_info

    def on_tick_error(self, error: BaseException) -> None:
        """After a failed tick, publish "not stalled" so a read error can't leave a stale banner."""
        self._publish(StallInfo(stalled=False))

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
        """Trigger the opt-in automatic Force-stop & reset once the kill window is exceeded (at most once)."""
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
            except FAIL_OPEN_ERRORS as e:
                log.warning(f"error during auto Force-stop & reset: {e}", exc_info=True)

    def _publish(self, info: StallInfo) -> None:
        """Store a fresh :class:`StallInfo` under the state lock for GUI readers."""
        with self._state_lock:
            self._stall_info = info

    def _default_progress_source(self):
        """Read latest-per-name DB records → (fingerprint, stuck_tests, running_pids, n_total)."""
        with PytestProcessInfoDB(self.data_dir) as db:
            infos = db.query(self.run_guid)
        latest = latest_info_per_name(infos)
        stuck: list[str] = []
        running_pids: list[int] = []
        n_terminal = 0
        n_running = 0
        max_started_ts = 0.0
        for name, info in latest.items():
            state = state_of(info)
            if state in TERMINAL_STATES:
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

        Delegates the persistent-handle subtree walk to the shared
        :class:`~pytest_fly.pytest_runner.process_monitor.SubtreeCpuSampler` (see its docstring
        for why handles must persist across ticks) and normalizes the raw psutil total to a
        single-core-equivalent 0-100 scale. ``None`` means "unknown" (priming/unreadable) and
        must never be treated as idle.
        """
        total = self._subtree_cpu.sample(pid)
        if total is None:
            return None
        return normalize_cpu_percent(total, get_performance_core_count())


# Backward-compatible aliases for the pre-extraction private names.
_StallConfig = StallConfig
_StallWatchdog = StallWatchdog
