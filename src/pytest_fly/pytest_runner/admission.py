"""
Admission gates — dispatch-time throttles (Part C of ``docs/pytest-fly-liveness-recovery-spec.md``).

Before dequeuing another test, a worker consults the enabled gates: process-count
(descendants of the controller), commit-charge (fraction of the system commit limit),
and CPU (fraction of total system CPU).  Gates only *defer* starting new tests — they
never cap how long a running test may take — and every signal is fail-open: a disabled
gate or an unreadable reading admits.

The poll/defer loop itself (with its min-1 forward-progress override and abort
predicate) stays with the worker thread in :mod:`pytest_runner`, which owns the timing
primitives; this module holds the configuration, the pure per-gate checks, and the
process-wide CPU sampler they share.
"""

import time
from dataclasses import dataclass
from threading import Lock

import psutil

from ..logger import get_logger
from .commit_memory import commit_charge_and_limit, subtree_process_count

log = get_logger()


@dataclass(frozen=True)
class AdmissionGateConfig:
    """Configuration for the dispatch-time admission gates (Part C).

    All gates default to disabled, so dispatch behavior is unchanged until a gate is
    explicitly enabled. The gates only *defer* starting new tests; they never cap how
    long a running test may take.
    """

    process_count_gate_enabled: bool = False
    max_descendant_processes: int = 0  # ignored when the process-count gate is disabled
    commit_gate_enabled: bool = False
    commit_gate_threshold: float = 0.90  # fraction of the system commit limit
    cpu_gate_enabled: bool = False
    cpu_gate_threshold: float = 0.90  # fraction of total system CPU utilization (0.0-1.0)


# System-wide CPU sampling for the CPU admission gate. ``psutil.cpu_percent(interval=None)``
# measures utilization since the *previous* call from this process, so the first reading is
# meaningless and rapid calls from several deferring worker threads would shrink the
# measurement window to noise. This process-wide cache primes once and re-samples at most
# once per ``_cpu_sample_min_interval_seconds``, returning the cached fraction in between.
_cpu_sample_lock = Lock()
_cpu_sample_min_interval_seconds = 1.0
_cpu_sample_primed = False
_cpu_sample_monotonic = 0.0
_cpu_sample_fraction: float | None = None


def system_cpu_fraction() -> float | None:
    """Return system-wide CPU utilization as a fraction (0.0-1.0), or ``None`` until primed.

    Callers must treat ``None`` as "signal unavailable" and fail open (admit), matching the
    other admission-gate readers.
    """
    global _cpu_sample_primed, _cpu_sample_monotonic, _cpu_sample_fraction
    with _cpu_sample_lock:
        now = time.monotonic()
        if not _cpu_sample_primed:
            psutil.cpu_percent(interval=None)  # prime; the first reading is meaningless
            _cpu_sample_primed = True
            _cpu_sample_monotonic = now
            return None
        if now - _cpu_sample_monotonic >= _cpu_sample_min_interval_seconds:
            _cpu_sample_fraction = psutil.cpu_percent(interval=None) / 100.0
            _cpu_sample_monotonic = now
        return _cpu_sample_fraction


class AdmissionGate:
    """Evaluates the enabled admission gates for one run (Part C).

    Pure check logic, shared by every worker thread of a run. Fail-open throughout:
    a disabled gate, an unreadable signal, or an unprimed CPU sampler admits.
    """

    def __init__(self, config: AdmissionGateConfig, controller_pid: int | None) -> None:
        """
        :param config: Gate enablement and thresholds.
        :param controller_pid: PID of the pytest-fly controller process, whose descendant
            tree the process-count gate measures. ``None`` disables that measurement.
        """
        self.config = config
        self.controller_pid = controller_pid

    def any_enabled(self) -> bool:
        """Return ``True`` when at least one gate is enabled (otherwise dispatch is ungated)."""
        cfg = self.config
        return cfg.process_count_gate_enabled or cfg.commit_gate_enabled or cfg.cpu_gate_enabled

    def checks_pass(self) -> bool:
        """Return ``True`` when every enabled gate allows dispatch (logical AND)."""
        return not self.failing_gates()

    def failing_gates(self) -> list[str]:
        """Return a description of each enabled gate currently at capacity, carrying the
        measured value and the threshold that fired (empty when dispatch is admitted)."""
        cfg = self.config
        failing = []
        if cfg.process_count_gate_enabled and (process_count_failure := self._process_count_failure()) is not None:
            failing.append(process_count_failure)
        if cfg.commit_gate_enabled and (commit_failure := self._commit_failure()) is not None:
            failing.append(commit_failure)
        if cfg.cpu_gate_enabled and (cpu_failure := self._cpu_failure()) is not None:
            failing.append(cpu_failure)
        return failing

    def _process_count_failure(self) -> str | None:
        """Return an at-capacity description if the controller's descendant tree has reached the ceiling, else ``None`` (fail-open)."""
        if self.controller_pid is None:
            return None
        count = subtree_process_count(self.controller_pid)
        if count <= 0:  # fail-open: tree could not be read
            return None
        if count < self.config.max_descendant_processes:
            return None
        return f"process-count ({count} of max {self.config.max_descendant_processes})"

    def _commit_failure(self) -> str | None:
        """Return an at-capacity description if system commit charge has reached the gate threshold, else ``None`` (fail-open)."""
        commit = commit_charge_and_limit()
        if commit is None:
            return None  # signal unavailable -> admit
        commit_total, commit_limit = commit
        if commit_limit <= 0:
            return None
        fraction = commit_total / commit_limit
        if fraction < self.config.commit_gate_threshold:
            return None
        return f"commit ({fraction:.1%}, threshold {self.config.commit_gate_threshold * 100:g}%)"

    def _cpu_failure(self) -> str | None:
        """Return an at-capacity description if system-wide CPU utilization has reached the gate threshold, else ``None`` (fail-open)."""
        cpu = system_cpu_fraction()
        if cpu is None:
            return None  # unprimed / unavailable -> admit
        if cpu < self.config.cpu_gate_threshold:
            return None
        return f"cpu ({cpu:.1%}, threshold {self.config.cpu_gate_threshold * 100:g}%)"


# Backward-compatible alias for the pre-extraction private name.
_AdmissionGateConfig = AdmissionGateConfig
