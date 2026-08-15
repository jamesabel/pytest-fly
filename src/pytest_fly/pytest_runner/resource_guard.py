"""
Resource guard — background monitor that automatically soft-stops a test run when the
system is running low on resources.

Two signals are watched:

- **Free disk space** on the drive holding the pytest-fly data directory (where the
  test-results DB and coverage data are written).  A full disk corrupts results and can
  wedge the whole machine.
- **Commit space** (physical RAM + pagefile — the real memory wall on Windows; see
  :mod:`pytest_fly.pytest_runner.commit_memory`).  Exhausting the commit limit surfaces
  as "the paging file is too small for this operation to complete" and crashed workers.

When either signal breaches its threshold for consecutive samples, the guard requests a
*soft stop*: running tests finish, queued tests do not start.  The stop is the same
cancelable soft stop the Stop button issues, so the user can override it with
**Cancel Stop**.  The guard triggers at most once per run (one-shot latch) — a canceled
auto-stop is a user override, not something to fight.

Every sampler is fail-open: an unreadable signal (non-Windows commit, disk read error)
never triggers a stop, matching the admission gates and the stall watchdog.
"""

import shutil
from dataclasses import dataclass
from pathlib import Path

from ..logger import get_logger
from .commit_memory import commit_charge_and_limit
from .const import BYTES_PER_GB
from .monitor_thread import MonitorThread

log = get_logger()

# Consecutive over-threshold samples required before the guard fires. Commit charge can
# spike transiently (e.g. while a subprocess forks), so a single bad sample is not
# treated as sustained pressure.
consecutive_breaches_to_trigger = 2


@dataclass(frozen=True)
class ResourceGuardConfig:
    """Configuration for the low-resource automatic soft stop.

    Disabled by default, so run behavior is unchanged until the guard is explicitly
    enabled.  A ``min_free_disk_gb`` of ``0`` disables the disk check; a
    ``commit_threshold`` of ``1.0`` effectively disables the commit check.
    """

    enabled: bool = False
    min_free_disk_gb: float = 10.0  # soft-stop when free disk space on the data-dir drive drops below this many GB
    commit_threshold: float = 0.95  # soft-stop when system commit charge exceeds this fraction of the commit limit


@dataclass(frozen=True)
class ResourceGuardInfo:
    """Snapshot of the resource guard's latest evaluation.  Read-only, GUI-facing.

    ``triggered`` and ``reason`` latch once the guard fires; the readings keep updating.
    """

    triggered: bool = False
    reason: str = ""  # human-readable description of what tripped the guard; empty until triggered
    free_disk_gb: float | None = None  # latest free-disk reading, None when unavailable
    commit_fraction: float | None = None  # latest commit charge as a fraction of the limit (0.0-1.0), None when unavailable


class ResourceGuard(MonitorThread):
    """Background thread that soft-stops the run when the system is low on resources.

    The daemon tick loop, stop signal, and fail-open error policy come from
    :class:`MonitorThread`; this class only evaluates the two resource signals and
    publishes a :class:`ResourceGuardInfo`.  The samplers are injectable so tests can
    drive :meth:`tick` with synthetic readings, host-independently.
    """

    def __init__(
        self,
        run_guid: str,
        disk_path: Path,
        config: ResourceGuardConfig,
        is_running_fn,
        soft_stop_fn,
        sample_interval: float,
        disk_free_sampler=None,
        commit_sampler=None,
    ) -> None:
        """
        :param run_guid: GUID identifying the overall test run (log context only).
        :param disk_path: Directory whose drive is checked for free space (the data dir).
        :param config: Thresholds and enablement.
        :param is_running_fn: Callable returning ``True`` while the run is in progress.
        :param soft_stop_fn: Callable that requests a cancelable soft stop of the run.
        :param sample_interval: Seconds between evaluations.
        :param disk_free_sampler: Callable returning free disk space in GB, or ``None``
            when unavailable.  Defaults to reading *disk_path*'s drive.
        :param commit_sampler: Callable returning the system commit charge as a fraction
            of the commit limit (0.0-1.0), or ``None`` when unavailable.
        """
        super().__init__(is_running_fn, sample_interval)
        self.run_guid = run_guid
        self.disk_path = disk_path
        self.config = config
        self._soft_stop_fn = soft_stop_fn
        self._disk_free_sampler = disk_free_sampler or self._default_disk_free_sampler
        self._commit_sampler = commit_sampler or self._default_commit_sampler

        self._info = ResourceGuardInfo()
        self._consecutive_breaches = 0
        self._triggered = False
        self._reason = ""

    def get_info(self) -> ResourceGuardInfo:
        """Return the most recently published :class:`ResourceGuardInfo`."""
        with self._state_lock:
            return self._info

    def tick(self) -> None:
        """Evaluate both resource signals once and publish a fresh :class:`ResourceGuardInfo`."""
        free_disk_gb = self._disk_free_sampler()
        commit_fraction = self._commit_sampler()

        breaches: list[str] = []
        if free_disk_gb is not None and self.config.min_free_disk_gb > 0 and free_disk_gb < self.config.min_free_disk_gb:
            breaches.append(f"free disk space {free_disk_gb:.1f} GB is below the {self.config.min_free_disk_gb:g} GB minimum")
        if commit_fraction is not None and commit_fraction > self.config.commit_threshold:
            breaches.append(f"commit charge at {commit_fraction:.0%} of the limit exceeds the {self.config.commit_threshold:.0%} threshold")

        if breaches:
            self._consecutive_breaches += 1
        else:
            self._consecutive_breaches = 0

        if not self._triggered and self._consecutive_breaches >= consecutive_breaches_to_trigger:
            self._triggered = True
            self._reason = "; ".join(breaches)
            log.warning(f"resource guard requesting soft stop: {self._reason} ({self.run_guid=})")
            self._soft_stop_fn()

        with self._state_lock:
            self._info = ResourceGuardInfo(triggered=self._triggered, reason=self._reason, free_disk_gb=free_disk_gb, commit_fraction=commit_fraction)

    def _default_disk_free_sampler(self) -> float | None:
        """Free space in GB on the drive holding ``disk_path``, or ``None`` on error (fail-open)."""
        try:
            return shutil.disk_usage(self.disk_path).free / BYTES_PER_GB
        except (OSError, ValueError):
            return None

    def _default_commit_sampler(self) -> float | None:
        """System commit charge as a fraction of the limit, or ``None`` when unavailable (fail-open)."""
        commit = commit_charge_and_limit()
        if commit is None:
            return None
        commit_total, commit_limit = commit
        if commit_limit <= 0:
            return None
        return commit_total / commit_limit
