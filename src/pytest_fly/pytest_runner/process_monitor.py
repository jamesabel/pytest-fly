"""
Resource monitor subprocess — periodically samples CPU and memory usage
of a target process and makes readings available via a shared queue.
"""

import time
from dataclasses import dataclass
from multiprocessing import Event, Process, Queue

from psutil import NoSuchProcess
from psutil import Process as PsutilProcess
from typeguard import typechecked

from ..logger import configure_child_logger


@dataclass(frozen=True)
class PytestProcessMonitorInfo:
    """A single CPU/memory sample captured by :class:`ProcessMonitor`."""

    run_guid: str  # pytest run GUID
    name: str  # process name
    pid: int | None  # process ID from the OS
    cpu_percent: float | None  # CPU usage percent
    memory_percent: float | None  # Memory usage percent
    time_stamp: float  # time stamp of the info update


def normalize_cpu_percent(cpu_percent: float, cores: int) -> float:
    """Normalize psutil's per-process CPU percent (0-100 * cores) to a single-core-equivalent 0-100 scale.

    psutil reports cpu_percent summed across cores (so a fully-busy 8-core machine reads ~800%); divide by
    the performance-core count to get a 0-100 figure and clamp, so one busy core on an 8-core box reads
    ~12.5% rather than ~100%.
    """
    return min(cpu_percent / max(cores, 1), 100.0)


class ProcessMonitor(Process):
    """
    Subprocess that periodically samples CPU and memory usage of a target
    process and makes the readings available via a shared :class:`~multiprocessing.Queue`.
    """

    @typechecked()
    def __init__(self, run_guid: str, name: str, pid: int, update_rate: float):
        """
        Monitor a process for things like CPU and memory usage.

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
        psutil_process.cpu_percent()  # initialize psutil's CPU usage (ignore the first 0.0)

        def put_process_monitor_data():
            """Take one CPU/memory sample and enqueue it."""
            if psutil_process.is_running():
                try:
                    # memory percent default is "rss"
                    cpu_percent = psutil_process.cpu_percent()
                    memory_percent = psutil_process.memory_percent()
                except NoSuchProcess:
                    cpu_percent = None
                    memory_percent = None
                if cpu_percent is not None and memory_percent is not None:
                    pytest_process_info = PytestProcessMonitorInfo(
                        run_guid=self._run_guid, name=self._name, pid=self._pid, cpu_percent=cpu_percent, memory_percent=memory_percent, time_stamp=time.time()
                    )
                    self.process_monitor_queue.put(pytest_process_info)

        while not self._stop_event.is_set():
            put_process_monitor_data()
            self._stop_event.wait(self._update_rate)
        put_process_monitor_data()

    def request_stop(self):
        """Signal the monitor loop to exit after the current sample."""
        self._stop_event.set()
