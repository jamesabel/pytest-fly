"""
System-wide resource monitor subprocess — periodically samples CPU, memory,
disk I/O, and network I/O and makes readings available via a shared queue.

Shares the same shape as :class:`pytest_fly.pytest_runner.process_monitor.ProcessMonitor`
(a :class:`multiprocessing.Process` with a `Queue`-based drain and a `request_stop()`
event) so the GUI can drain it with identical plumbing.
"""

import time
from dataclasses import dataclass
from multiprocessing import Event, Process, Queue

import psutil
from typeguard import typechecked


@dataclass(frozen=True)
class SystemMonitorSample:
    """A single system-wide resource sample."""

    time_stamp: float
    cpu_percent: float  # 0.0 - 100.0 (psutil.cpu_percent; system-wide)
    memory_percent: float  # 0.0 - 100.0 (psutil.virtual_memory().percent)
    memory_used_gb: float  # GiB used (psutil.virtual_memory().used)
    memory_total_gb: float  # GiB total (psutil.virtual_memory().total)
    disk_read_mbps: float  # MB/s read since the previous sample
    disk_write_mbps: float  # MB/s written since the previous sample
    net_sent_mbps: float  # MB/s sent since the previous sample
    net_recv_mbps: float  # MB/s received since the previous sample


_BYTES_PER_MB = 1024.0 * 1024.0
_BYTES_PER_GB = 1024.0 * 1024.0 * 1024.0


class SystemMonitor(Process):
    """Subprocess that periodically samples system-wide resource usage."""

    @typechecked()
    def __init__(self, update_rate: float = 1.0):
        """
        :param update_rate: Seconds between samples.  Fixed cadence, independent of the GUI refresh rate,
            so charts stay smooth even when the GUI refresh rate is tuned up.
        """
        super().__init__(daemon=True)
        self._update_rate = update_rate
        self._stop_event = Event()
        self.system_monitor_queue: Queue = Queue()

    def run(self):
        """Sample resources at ``_update_rate`` intervals until stop is requested."""
        psutil.cpu_percent(interval=None)  # prime psutil's CPU counter; ignore the first 0.0

        prev_disk = psutil.disk_io_counters()
        prev_net = psutil.net_io_counters()
        prev_time = time.time()

        while not self._stop_event.is_set():
            self._stop_event.wait(self._update_rate)
            if self._stop_event.is_set():
                break

            now = time.time()
            elapsed = max(now - prev_time, 1e-6)

            cpu_pct = psutil.cpu_percent(interval=None)
            vm = psutil.virtual_memory()
            mem_pct = vm.percent
            mem_used_gb = vm.used / _BYTES_PER_GB
            mem_total_gb = vm.total / _BYTES_PER_GB

            cur_disk = psutil.disk_io_counters()
            cur_net = psutil.net_io_counters()

            if cur_disk is not None and prev_disk is not None:
                disk_read_mbps = max(cur_disk.read_bytes - prev_disk.read_bytes, 0) / _BYTES_PER_MB / elapsed
                disk_write_mbps = max(cur_disk.write_bytes - prev_disk.write_bytes, 0) / _BYTES_PER_MB / elapsed
            else:
                disk_read_mbps = 0.0
                disk_write_mbps = 0.0

            if cur_net is not None and prev_net is not None:
                net_sent_mbps = max(cur_net.bytes_sent - prev_net.bytes_sent, 0) / _BYTES_PER_MB / elapsed
                net_recv_mbps = max(cur_net.bytes_recv - prev_net.bytes_recv, 0) / _BYTES_PER_MB / elapsed
            else:
                net_sent_mbps = 0.0
                net_recv_mbps = 0.0

            sample = SystemMonitorSample(
                time_stamp=now,
                cpu_percent=cpu_pct,
                memory_percent=mem_pct,
                memory_used_gb=mem_used_gb,
                memory_total_gb=mem_total_gb,
                disk_read_mbps=disk_read_mbps,
                disk_write_mbps=disk_write_mbps,
                net_sent_mbps=net_sent_mbps,
                net_recv_mbps=net_recv_mbps,
            )
            self.system_monitor_queue.put(sample)

            prev_disk = cur_disk
            prev_net = cur_net
            prev_time = now

    def request_stop(self):
        """Signal the monitor loop to exit after the current sample."""
        self._stop_event.set()
