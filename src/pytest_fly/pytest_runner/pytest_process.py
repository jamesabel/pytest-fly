import contextlib
import io
import shutil
import time
from multiprocessing import Process
from pathlib import Path
from queue import Empty

import pytest
from coverage import Coverage
from typeguard import typechecked

from ..__version__ import application_name
from ..interfaces import PytestProcessInfo, PyTestFlyExitCode
from ..logger import get_logger
from ..db import PytestProcessInfoDB
from .process_monitor import ProcessMonitor

log = get_logger(application_name)


class PytestProcess(Process):
    """
    A process that performs a pytest run.
    """

    @typechecked()
    def __init__(self, run_guid: str, test: Path | str, data_dir: Path, update_rate: float) -> None:
        """
        Pytest process for a single pytest test.

        :param run_guid: the pytest run this process is associated with (same GUID for all tests in a pytest run)
        :param test: the test to run
        :param data_dir: the directory to store coverage data in
        :param update_rate: the update rate for the process monitor
        """
        super().__init__(name=str(test))
        self.data_dir = data_dir
        self.run_guid = run_guid
        self.update_rate = update_rate

        self._process_monitor_process = None

    def run(self) -> None:

        # start the process monitor to monitor things like CPU and memory usage
        self._process_monitor_process = ProcessMonitor(self.run_guid, self.name, self.pid, self.update_rate)
        self._process_monitor_process.start()

        # update the pytest process info to show that the test is running
        with PytestProcessInfoDB(self.data_dir) as db:
            pytest_process_info = PytestProcessInfo(self.run_guid, self.name, self.pid, PyTestFlyExitCode.NONE, None, time_stamp=time.time())
            db.write(pytest_process_info)

        # Finally, actually run pytest!
        # Redirect stdout and stderr so nothing goes to the console.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):

            # create a temp coverage file and then move it so if the file exists, the content is complete (the save is not necessarily instantaneous and atomic)
            coverage_file_path = Path(self.data_dir, f"{self.name}.coverage")
            coverage_temp_file_path = Path(self.data_dir, f"{self.name}.temp")
            coverage_temp_file_path.unlink(missing_ok=True)
            coverage = Coverage(coverage_temp_file_path)
            coverage.start()

            exit_code = pytest.main([self.name])

            coverage.stop()
            coverage.save()
            coverage_file_path.unlink(missing_ok=True)
            shutil.move(coverage_temp_file_path, coverage_file_path)

        output: str = buf.getvalue()

        # stop the process monitor
        self._process_monitor_process.request_stop()
        self._process_monitor_process.join(100.0)  # plenty of time for the monitor to stop
        if self._process_monitor_process.is_alive():
            log.warning(f"{self._process_monitor_process} is alive")

        # drain the process monitor queue to compute peak CPU and memory usage
        cpu_samples = []
        memory_samples = []
        while True:
            try:
                monitor_info = self._process_monitor_process.process_monitor_queue.get_nowait()
                if monitor_info.cpu_percent is not None:
                    cpu_samples.append(monitor_info.cpu_percent)
                if monitor_info.memory_percent is not None:
                    memory_samples.append(monitor_info.memory_percent)
            except Empty:
                break
        peak_cpu = max(cpu_samples) if cpu_samples else None
        peak_memory = max(memory_samples) if memory_samples else None

        # update the pytest process info to show that the test has finished
        with PytestProcessInfoDB(self.data_dir) as db:
            pytest_process_info = PytestProcessInfo(self.run_guid, self.name, self.pid, exit_code, output, time.time(), peak_cpu, peak_memory)
            db.write(pytest_process_info)

        log.debug(f"{self.name=},{self.name},{exit_code=},{output=}")
