"""
Resource monitor subprocess — periodically samples CPU and memory usage
of a target process and makes readings available via a shared queue.
"""

import time
from dataclasses import dataclass
from multiprocessing import Event, Process, Queue

import psutil
from psutil import NoSuchProcess
from psutil import Process as PsutilProcess
from typeguard import typechecked

from ..logger import configure_child_logger
from .commit_memory import subtree_commit


@dataclass(frozen=True)
class PytestProcessMonitorInfo:
    """A single CPU/memory sample captured by :class:`ProcessMonitor`."""

    run_guid: str  # pytest run GUID
    name: str  # process name
    pid: int | None  # process ID from the OS
    cpu_percent: float | None  # CPU usage percent of the process subtree (raw psutil scale: one full core == 100, so a multi-core subtree can exceed 100)
    memory_percent: float | None  # Memory usage percent
    time_stamp: float  # time stamp of the info update
    commit_bytes: int | None = None  # commit charge of the process subtree in bytes (Windows: pagefile)


@typechecked()
def normalize_cpu_percent(cpu_percent: float, cores: int) -> float:
    """Normalize psutil's per-process CPU percent (0-100 * cores) to a single-core-equivalent 0-100 scale.

    psutil reports cpu_percent summed across cores (so a fully-busy 8-core machine reads ~800%); divide by
    the performance-core count to get a 0-100 figure and clamp, so one busy core on an 8-core box reads
    ~12.5% rather than ~100%.
    """
    return min(cpu_percent / max(cores, 1), 100.0)


class SubtreeCpuSampler:
    """Samples whole-subtree CPU percent (raw psutil scale) for arbitrary root pids.

    psutil's ``cpu_percent(interval=None)`` reports usage as a delta against the *same*
    :class:`psutil.Process` object's previous call, so every sampled process — each root
    **and each descendant** — needs a handle that persists across samples (all cached
    here). Re-creating child handles each sample would make them perpetually report the
    meaningless first-call ``0.0``, silently dropping the CPU of any subprocess/.exe a
    test spawns (a test that offloads its work to a child would always read idle).
    Newly-seen descendants are primed (they contribute ``0.0`` that sample, real readings
    thereafter); handles whose process has exited are dropped.

    :meth:`sample` returns ``None`` when the root pid is newly seen (its first reading is
    meaningless) or unreadable — callers must treat ``None`` as "unknown", never "idle".
    Shared by :class:`ProcessMonitor` (raw totals) and the stall watchdog (which
    normalizes via :func:`normalize_cpu_percent`).
    """

    def __init__(self) -> None:
        self._procs: dict[int, psutil.Process] = {}

    def sample(self, pid: int) -> float | None:
        """Return the subtree's summed CPU percent, or ``None`` when priming/unreadable."""
        try:
            root = self._procs.get(pid)
            first_sight = root is None
            if root is None:
                root = psutil.Process(pid)
                self._procs[pid] = root
                root.cpu_percent(interval=None)  # prime; the first reading is meaningless
            total = 0.0 if first_sight else root.cpu_percent(interval=None)
            for child in root.children(recursive=True):
                cached = self._procs.get(child.pid)
                try:
                    if cached is None:
                        # New descendant: cache + prime now so the next sample reads real usage.
                        self._procs[child.pid] = child
                        child.cpu_percent(interval=None)
                    else:
                        total += cached.cpu_percent(interval=None)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    self._procs.pop(child.pid, None)
            return None if first_sight else total
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
            # ValueError: psutil rejects non-positive PIDs.
            self._procs.pop(pid, None)
            return None


class ProcessMonitor(Process):
    """
    Subprocess that periodically samples CPU and memory usage of a target
    process and makes the readings available via a shared :class:`~multiprocessing.Queue`.
    """

    @typechecked()
    def __init__(self, run_guid: str, name: str, pid: int, update_rate: float):
        """
        Monitor a process for things like CPU and memory usage.

        :param run_guid: the pytest run GUID stamped onto every sample
        :param name: the name of the process to monitor
        :param pid: the process ID of the process to monitor
        :param update_rate: the rate at which to send back updates
        """
        super().__init__()
        self._run_guid = run_guid
        self._name = name
        self._pid = pid
        self._update_rate = update_rate
        self._stop_event = Event()
        self.process_monitor_queue = Queue()  # Queue to send back process monitor info

    def run(self):
        """Sample CPU and memory at ``_update_rate`` intervals until stop is requested."""
        configure_child_logger(f"process_monitor-{self._pid}.log")

        psutil_process = PsutilProcess(self._pid)

        # Shared subtree sampler: persistent handles for the root and every descendant so
        # interval=None CPU deltas stay valid (see SubtreeCpuSampler). Its first sample
        # returns None (priming), so the first loop iteration enqueues nothing.
        cpu_sampler = SubtreeCpuSampler()

        def put_process_monitor_data():
            """Take one CPU/memory sample and enqueue it."""
            if psutil_process.is_running():
                try:
                    # memory percent default is "rss"
                    memory_percent = psutil_process.memory_percent()
                except NoSuchProcess:
                    memory_percent = None
                cpu_percent = cpu_sampler.sample(self._pid)
                if cpu_percent is not None and memory_percent is not None:
                    # Commit charge of the whole process subtree (the test may spawn children).
                    commit_bytes = subtree_commit(self._pid)
                    pytest_process_info = PytestProcessMonitorInfo(
                        run_guid=self._run_guid, name=self._name, pid=self._pid, cpu_percent=cpu_percent, memory_percent=memory_percent, time_stamp=time.time(), commit_bytes=commit_bytes
                    )
                    self.process_monitor_queue.put(pytest_process_info)

        while not self._stop_event.is_set():
            put_process_monitor_data()
            self._stop_event.wait(self._update_rate)
        put_process_monitor_data()

    def request_stop(self):
        """Signal the monitor loop to exit after the current sample."""
        self._stop_event.set()
