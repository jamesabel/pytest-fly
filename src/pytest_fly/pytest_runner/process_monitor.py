import time
from multiprocessing import Process, Queue, Event
from dataclasses import dataclass

from psutil import NoSuchProcess, Process as PsutilProcess
from typeguard import typechecked


@dataclass(frozen=True)
class PytestProcessMonitorInfo:
    run_guid: str  # pytest run GUID
    name: str  # process name
    pid: int | None  # process ID from the OS
    cpu_percent: float | None  # CPU usage percent
    memory_percent: float | None  # Memory usage percent
    time_stamp: float  # time stamp of the info update


class ProcessMonitor(Process):

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

        psutil_process = PsutilProcess(self._pid)
        psutil_process.cpu_percent()  # initialize psutil's CPU usage (ignore the first 0.0)

        def put_process_monitor_data():
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
        self._stop_event.set()
