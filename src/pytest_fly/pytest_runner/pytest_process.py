import contextlib
import io
import shutil
import time
from enum import StrEnum, auto
from multiprocessing import Process, Queue
from pathlib import Path
from dataclasses import dataclass

import pytest
from pytest import ExitCode
from coverage import Coverage
from typeguard import typechecked

from pytest_fly.__version__ import application_name
from pytest_fly.logger import get_logger

from .process_monitor import ProcessMonitor
from pytest_fly.guid import generate_uuid

log = get_logger(application_name)


@dataclass(frozen=True)
class PytestProcessInfo:
    """
    Information about a pytest process.
    """

    run_guid: str  # the pytest run GUID this process is associated with
    name: str  # process name (usually the test name)
    pid: int | None  # process ID from the OS
    instance_uuid: str  # unique identifier for this process instance
    exit_code: ExitCode | None  # exit code from pytest, None if the test is still running
    output: str | None  # output from the pytest run, None if the test is still running
    time_stamp: float  # time stamp of the info update


class PytestProcess(Process):
    """
    A process that performs a pytest run.
    """

    @typechecked()
    def __init__(self, run_guid: str, test: Path | str, coverage_parent_directory: Path, update_rate: float) -> None:
        """
        Pytest process for a single pytest test.

        :param run_guid: the pytest run this process is associated with (same GUID for all tests in a pytest run)
        :param test: the test to run
        :param coverage_parent_directory: the directory to store coverage data in
        :param update_rate: the update rate for the process monitor
        """
        super().__init__(name=str(test))
        self.coverage_parent_directory = coverage_parent_directory
        self.run_guid = run_guid
        self.update_rate = update_rate

        # caller can access the Queue directly, for example to do a .get() (with a timeout) so the results are immediately available when status is put into the Queue
        self.pytest_monitor_queue = Queue()

        self._process_monitor_process = None

    def run(self) -> None:

        process_uuid = generate_uuid()

        # start the process monitor to monitor things like CPU and memory usage
        self._process_monitor_process = ProcessMonitor(self.name, self.pid, process_uuid, self.update_rate)
        self._process_monitor_process.start()

        # update the pytest process info to show that the test is running
        pytest_process_info = PytestProcessInfo(self.run_guid, self.name, self.pid, instance_uuid=process_uuid, exit_code=None, output=None, time_stamp=time.time())
        self.pytest_monitor_queue.put(pytest_process_info)

        coverage_data_directory = Path(self.coverage_parent_directory, "coverage")
        coverage_data_directory.mkdir(parents=True, exist_ok=True)

        # Finally, actually run pytest!
        # Redirect stdout and stderr so nothing goes to the console.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):

            # create a temp coverage file and then move it so if the file exists, the content is complete (the save is not necessarily instantaneous and atomic)
            coverage_file_path = Path(coverage_data_directory, f"{self.name}.coverage")
            coverage_temp_file_path = Path(coverage_data_directory, f"{self.name}.temp")
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
            log.error(f"{self._process_monitor_process} is alive")

        # update the pytest process info to show that the test has finished
        pytest_process_info = PytestProcessInfo(self.run_guid, self.name, self.pid, process_uuid, exit_code, output, time_stamp=time.time())
        self.pytest_monitor_queue.put(pytest_process_info)

        log.debug(f"{self.name=},{self.name},{exit_code=},{output=}")


class PytestProcessState(StrEnum):
    """
    Represents the state of a test process.
    """

    UNKNOWN = auto()  # unknown state
    QUEUED = auto()  # queued to be run by the scheduler
    RUNNING = auto()  # test is currently running
    FINISHED = auto()  # test has finished
    TERMINATED = auto()  # test was terminated
