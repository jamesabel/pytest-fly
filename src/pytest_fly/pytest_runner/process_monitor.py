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

from ..faults import enable_faulthandler
from ..logger import configure_child_logger
from .commit_memory import ProcessHandleCache, subtree_commit, subtree_members


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

    Subtree membership comes from :func:`~.commit_memory.subtree_members` (a pid→ppid
    snapshot plus one native ``create_time`` read per member), never
    ``children(recursive=True)`` — ``children()`` constructs a fresh ``psutil.Process`` per
    descendant per call, and each construction runs a native init (a ``create_time``
    identity read) that a native GC crash has been observed inside (Windows, Python 3.14).
    Here handles live in a :class:`~.commit_memory.ProcessHandleCache`: constructed once at
    first sight of a process identity and reused for every later sample.  The membership
    walk's creation times are what the cache checks each handle against, so a recycled pid
    (a new worker or helper that inherited a dead one's pid) is re-primed as a new process
    instead of being read through the dead one's handle — ``cpu_percent`` itself would not
    notice and would report a meaningless cross-process delta.  Handles whose pid left the
    subtree are dropped.
    """

    def __init__(self) -> None:
        self._handles = ProcessHandleCache()
        self._members: dict[int, set[int]] = {}  # last-seen subtree membership per sampled root

    def sample(self, pid: int) -> float | None:
        """Return the subtree's summed CPU percent, or ``None`` when priming/unreadable."""
        members = subtree_members(pid)
        if not members:
            # Root gone/unreadable (or its pid non-positive).  Never a reading: a partial
            # total here would be taken for a genuine idle sample.
            self._drop_departed(pid, set())
            self._handles.drop(pid)
            return None
        total: float | None = 0.0
        for member_pid, member_ctime in members.items():
            # ``holds`` is False for a new process *and* for a recycled pid (identity changed):
            # both get a fresh handle whose first reading only primes the delta.
            first_sight = not self._handles.holds(member_pid, member_ctime)
            handle = self._handles.get(member_pid, member_ctime)
            if handle is None:
                if member_pid == pid:
                    total = None  # the root itself is unreadable: no sample this tick
                continue
            try:
                reading = handle.cpu_percent(interval=None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                self._handles.drop(member_pid)
                if member_pid == pid:
                    total = None
                continue
            if first_sight:
                if member_pid == pid:
                    total = None  # the root's first reading is meaningless: no sample this tick
            elif total is not None:
                total += reading
        self._drop_departed(pid, set(members))
        return total

    def _drop_departed(self, pid: int, member_pids: set[int]) -> None:
        """Drop cached handles for pids that left *pid*'s subtree since the previous sample.

        Keeps the cache bounded under process churn — without this, a handle for an exited
        descendant would linger until its pid was recycled and the identity check evicted it.
        """
        for departed_pid in self._members.get(pid, set()) - member_pids - {pid}:
            self._handles.drop(departed_pid)
        if member_pids:
            self._members[pid] = member_pids
        else:
            self._members.pop(pid, None)


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
        # daemon=True: multiprocessing terminates daemon children when their parent exits.
        # As a non-daemon child, any unguarded exception unwinding PytestProcess.run() made
        # multiprocessing's exit handler *join* this monitor - whose loop never ends on its
        # own - so the test process hung forever with no terminal record.
        super().__init__(daemon=True)
        self._run_guid = run_guid
        self._name = name
        self._pid = pid
        self._update_rate = update_rate
        self._stop_event = Event()
        self.process_monitor_queue = Queue()  # Queue to send back process monitor info

    def run(self):
        """Sample CPU and memory at ``_update_rate`` intervals until stop is requested."""
        configure_child_logger(f"process_monitor-{self._pid}.log")
        enable_faulthandler()  # reads PYTEST_FLY_FAULTHANDLER from the inherited environment

        psutil_process = PsutilProcess(self._pid)

        # Shared subtree sampler: persistent handles for the root and every descendant so
        # interval=None CPU deltas stay valid (see SubtreeCpuSampler). Its first sample
        # returns None (priming), so the first loop iteration enqueues nothing.
        cpu_sampler = SubtreeCpuSampler()

        # Persistent handles for the per-sample commit read too — constructed once per pid,
        # not once per member per sample (see ProcessHandleCache).
        commit_handles = ProcessHandleCache()

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
                    commit_bytes = subtree_commit(self._pid, commit_handles)
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
