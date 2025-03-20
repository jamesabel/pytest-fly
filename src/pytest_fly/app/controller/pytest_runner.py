from multiprocessing import Process, Queue, Event
import io
import contextlib
from pathlib import Path
from queue import Empty
import time
from copy import deepcopy

import psutil
import pytest
from pytest import ExitCode
from PySide6.QtCore import QObject, Signal, Slot, QTimer, QCoreApplication
from typeguard import typechecked
from psutil import Process as PsutilProcess
from psutil import NoSuchProcess
import appdirs

from ..logging import get_logger
from ...common import (
    get_guid,
    PytestProcessInfo,
    PytestProcessState,
    RunParameters,
    upsert_pytest_process_current_info,
    query_pytest_process_current_info,
    RunMode,
    delete_pytest_process_current_info,
)
from ..preferences import get_pref
from ..test_list import get_tests
from ...__version__ import application_name, author


log = get_logger()


class _PytestProcessMonitor(Process):

    def __init__(self, name: str, pid: int, update_rate: float, process_monitor_queue: Queue):
        """
        Monitor a process for things like CPU and memory usage.

        :param name: the name of the process to monitor
        :param pid: the process ID of the process to monitor
        :param update_rate: the rate at which to send back updates
        :param process_monitor_queue: the queue to send updates to
        """
        super().__init__()
        self._name = name
        self._pid = pid
        self._update_rate = update_rate
        self._psutil_process = None
        self._process_monitor_queue = process_monitor_queue
        self._stop_event = Event()

    def run(self):

        def put_process_monitor_data():
            if self._psutil_process.is_running():
                try:
                    # memory percent default is "rss"
                    cpu_percent = self._psutil_process.cpu_percent()
                    memory_percent = self._psutil_process.memory_percent()
                except NoSuchProcess:
                    cpu_percent = None
                    memory_percent = None
                if cpu_percent is not None and memory_percent is not None:
                    pytest_process_info = PytestProcessInfo(self._name, pid=self._pid, cpu_percent=cpu_percent, memory_percent=memory_percent)
                    self._process_monitor_queue.put(pytest_process_info)

        self._psutil_process = PsutilProcess(self._pid)
        self._psutil_process.cpu_percent()  # initialize psutil's CPU usage (ignore the first 0.0)

        while not self._stop_event.is_set():
            put_process_monitor_data()
            self._stop_event.wait(self._update_rate)
        put_process_monitor_data()

    def request_stop(self):
        self._stop_event.set()


class _PytestProcess(Process):
    """
    A process that performs a pytest run.
    """

    @typechecked()
    def __init__(self, test: Path | str, update_rate: float, pytest_monitor_queue: Queue) -> None:
        """
        :param test: the test to run
        :param update_rate: the rate at which to update the monitor
        :param pytest_monitor_queue: the queue to send pytest updates to
        """
        super().__init__(name=str(test))
        self.update_rate = update_rate
        self.pytest_monitor_queue = pytest_monitor_queue

        self._process_monitor_process = None

    def run(self) -> None:

        # start the process monitor to monitor things like CPU and memory usage
        self._process_monitor_process = _PytestProcessMonitor(self.name, self.pid, self.update_rate, self.pytest_monitor_queue)
        self._process_monitor_process.start()

        # update the pytest process info to show that the test is running
        pytest_process_info = PytestProcessInfo(self.name, PytestProcessState.RUNNING, self.pid, start=time.time())
        self.pytest_monitor_queue.put(pytest_process_info)

        # Finally, actually run pytest!
        # Redirect stdout and stderr so nothing goes to the console.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            exit_code = pytest.main([self.name])
        output: str = buf.getvalue()
        end = time.time()

        # stop the process monitor
        self._process_monitor_process.request_stop()
        self._process_monitor_process.join(100.0)  # plenty of time for the monitor to stop
        if self._process_monitor_process.is_alive():
            log.error(f"{self._process_monitor_process} is alive")

        # update the pytest process info to show that the test has finished
        pytest_process_info = PytestProcessInfo(self.name, PytestProcessState.FINISHED, self.pid, exit_code, output, end=end)
        self.pytest_monitor_queue.put(pytest_process_info)

        log.debug(f"{self.name=},{self.name},{exit_code=},{output=}")


class PytestRunnerWorker(QObject):
    """
    Worker that runs pytest tests in separate processes.
    """

    # signals to request pytest actions
    _request_run_signal = Signal(RunParameters)  # request run, passing in the run parameters
    _request_stop_signal = Signal()  # request stop
    request_exit_signal = Signal()  # request exit (not private since it's connected to the thread quit slot)

    update_signal = Signal(PytestProcessInfo)  # caller connects to this signal to get updates (e.g., for the GUI)

    @typechecked()
    def request_run(self, run_parameters: RunParameters):
        self.run_guid = run_parameters.run_guid
        self._request_run_signal.emit(run_parameters)

    def request_stop(self):
        self._request_stop_signal.emit()

    def request_exit(self):
        self._scheduler_timer.stop()
        self._scheduler_timer.deleteLater()
        self.request_exit_signal.emit()

    @typechecked()
    def __init__(self, tests: list[str] | None = None) -> None:
        """
        Pytest runner worker.

        :param tests: the tests to run
        """
        super().__init__()

        self.pytest_process_dict_save_path = Path(appdirs.user_data_dir(application_name, author), "pytest_process_dict.pickle")

        if tests is None:
            self.tests = get_tests()
        else:
            self.tests = tests

        self.pytest_monitor_queue = Queue()  # monitor data for the pytest processes

        self._processes = {}  # dict of running processes

        self.max_processes = 1
        self.run_guid = None

        self._request_run_signal.connect(self._run)
        self._request_stop_signal.connect(self._stop)

        self._scheduler_timer = QTimer()
        self._scheduler_timer.timeout.connect(self._scheduler)
        self._scheduler_timer.start(1000)

    @Slot()
    def _run(self, run_parameters: RunParameters):
        """
        Run tests (puts the tests in the queue).
        """
        log.info(f"{run_parameters=}")

        self.run_guid = get_guid()

        self.max_processes = max(run_parameters.max_processes, 1)  # ensure at least one process

        self._stop()  # in case any tests are already running

        pref = get_pref()
        mode = pref.run_mode

        for test in self.tests:
            if mode == RunMode.RESTART:
                add_test = True
            else:
                pytest_process_infos = query_pytest_process_current_info(name=test)
                if len(pytest_process_infos) > 0:
                    pytest_process_info = pytest_process_infos[-1]
                    add_test = pytest_process_info.state != PytestProcessState.FINISHED or pytest_process_info.exit_code != ExitCode.OK
                    self.update_pytest_process_info(pytest_process_info, False)
                else:
                    add_test = True
            if add_test:
                # start over for this test
                pytest_process_info = PytestProcessInfo(name=test, state=PytestProcessState.QUEUED)
                self.update_pytest_process_info(pytest_process_info, True)

    @Slot()
    def _stop(self):
        """
        Stop all running tests.
        """

        for test in self.tests:
            pytest_process_infos = query_pytest_process_current_info(name=test)
            if len(pytest_process_infos) > 0:
                pytest_process_info = pytest_process_infos[-1]
                if pytest_process_info.state == PytestProcessState.RUNNING:
                    try:
                        process = psutil.Process(pytest_process_info.pid)
                        log.info(f"terminating {test}")
                        try:
                            process.terminate()
                        except PermissionError:
                            log.warning(f"PermissionError terminating {test}")
                        log.info(f"joining {test}")
                        try:
                            process.wait(10)
                        except PermissionError:
                            log.warning(f"PermissionError joining {test}")
                    except NoSuchProcess:
                        pass
                    new_pytest_process_info = PytestProcessInfo(name=test, state=PytestProcessState.TERMINATED)
                    self.update_pytest_process_info(new_pytest_process_info, False)
        self._processes.clear()

    @Slot()
    def _scheduler(self):
        """
        Schedule tests to run.
        """

        # determine what tests to run
        tests_queued = []
        tests_running = []
        for test in self.tests:
            pytest_process_infos = query_pytest_process_current_info(name=test)
            if len(pytest_process_infos) > 0:
                most_recent_pytest_process_info = pytest_process_infos[-1]
                if most_recent_pytest_process_info.state == PytestProcessState.QUEUED:
                    tests_queued.append(test)
                elif most_recent_pytest_process_info.state == PytestProcessState.RUNNING:
                    tests_running.append(test)
                else:
                    # test is finished or terminated
                    pass
        max_number_of_tests_to_run = max(self.max_processes - len(tests_running), 0)
        tests_to_run = sorted(tests_queued)[:max_number_of_tests_to_run]

        # run tests
        if len(tests_to_run) > 0:
            pref = get_pref()
            refresh_rate = pref.refresh_rate
            for test in tests_to_run:

                log.debug(f"{test} is queued - starting")

                log.debug(f"starting {test}")
                pytest_process_info = PytestProcessInfo(name=test, state=PytestProcessState.RUNNING)
                self.update_pytest_process_info(pytest_process_info, False)

                # we don't generally access self.processes, but we need to keep a reference to the process and ensure it stays alive
                self._processes[test] = _PytestProcess(test, refresh_rate, self.pytest_monitor_queue)
                self._processes[test].start()

        # update UI
        try:
            while (pytest_process_info := self.pytest_monitor_queue.get(False)) is not None:
                self.update_pytest_process_info(pytest_process_info, False)
        except Empty:
            pass

    def update_pytest_process_info(self, updated_pytest_process_info: PytestProcessInfo, initialize: bool):
        """
        Update the PytestProcessInfo for a test.
        If the test is new, add it to the global dict. Only use non-None values to update the existing test.

        :param updated_pytest_process_info: the updated PytestProcessInfo
        :param initialize: True if the test is new
        """
        name = updated_pytest_process_info.name

        if initialize:
            delete_pytest_process_current_info(name)

        pytest_process_infos = query_pytest_process_current_info(name=name)

        if initialize or len(pytest_process_infos) < 1:
            pytest_process_info = updated_pytest_process_info
        else:
            # update most recent test info
            pytest_process_info = deepcopy(pytest_process_infos[-1])
            for attribute in updated_pytest_process_info.__dataclass_fields__.keys():  # update the attributes
                if (value := getattr(updated_pytest_process_info, attribute)) is not None:
                    setattr(pytest_process_info, attribute, value)

        pytest_process_info.time_stamp = time.time()

        upsert_pytest_process_current_info(pytest_process_info)
        self.update_signal.emit(pytest_process_info)
        QCoreApplication.processEvents()
