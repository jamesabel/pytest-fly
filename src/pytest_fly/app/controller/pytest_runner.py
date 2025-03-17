from multiprocessing import Process, Queue, Event, Manager, Lock
import io
import contextlib
from pathlib import Path
from queue import Empty
import time
from copy import deepcopy

import psutil
import pytest
from _pytest.config import ExitCode
from PySide6.QtCore import QObject, Signal, Slot, QTimer, QCoreApplication
from typeguard import typechecked
from psutil import Process as PsutilProcess
from psutil import NoSuchProcess

from ..logging import get_logger
from ...common import get_guid, PytestProcessInfo, PytestProcessState, RunParameters, RunMode
from ..preferences import get_pref
from ..test_list import get_tests
from ...db import write_test_status


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

        if tests is None:
            self.tests = get_tests()
        else:
            self.tests = tests

        self.test_queue = Queue()  # tests to be run
        self.pytest_monitor_queue = Queue()  # monitor data for the pytest processes

        self.pytest_processes_manager = Manager()  # dict values are PytestProcessInfo
        self.pytest_processes_dict = self.pytest_processes_manager.dict()

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

        pytest_processes_dict = deepcopy(self.pytest_processes_dict)
        for test in self.tests:
            add_test = True
            if run_parameters.run_mode == RunMode.RESUME and (pytest_process_info := pytest_processes_dict.get(test)) is not None:
                if pytest_process_info.state == PytestProcessState.FINISHED and pytest_process_info.exit_code == ExitCode.OK:
                    add_test = False
            if add_test:
                pytest_process_info = PytestProcessInfo(name=test, state=PytestProcessState.QUEUED)
                self.update_pytest_process_info(pytest_process_info, True)  # initialize
                self.test_queue.put(test)

        if self.test_queue.qsize() == 0:
            log.warning("No tests to run")

    @Slot()
    def _stop(self):
        """
        Stop all running tests.
        """

        for test, pytest_process in self.pytest_processes_dict.items():
            if pytest_process.state == PytestProcessState.RUNNING:
                try:
                    process = psutil.Process(pytest_process.pid)
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
                pytest_process_info = PytestProcessInfo(name=test, state=PytestProcessState.TERMINATED)
                self.update_pytest_process_info(pytest_process_info, False)
        self._processes.clear()
        log.info(f"exiting")

    @Slot()
    def _scheduler(self):
        """
        Schedule tests to run.
        """

        # determine what tests to run
        running_processes = [p for p in self.pytest_processes_dict.values() if p.state == PytestProcessState.RUNNING]
        max_number_of_tests_to_run = max(self.max_processes - len(running_processes), 0)
        tests_to_run = []
        try:
            while len(tests_to_run) < max_number_of_tests_to_run:
                if (test := self.test_queue.get(False)) is None:
                    break
                else:
                    tests_to_run.append(test)
        except Empty:
            pass

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

        if initialize or name not in self.pytest_processes_dict:
            new_pytest_process_info = updated_pytest_process_info
        else:
            # update existing test info
            new_pytest_process_info = self.pytest_processes_dict[name]
            for attribute in updated_pytest_process_info.__dataclass_fields__.keys():  # update the attributes
                if (value := getattr(updated_pytest_process_info, attribute)) is not None:
                    setattr(new_pytest_process_info, attribute, value)

        new_pytest_process_info.time_stamp = time.time()

        with Lock():
            self.pytest_processes_dict[name] = new_pytest_process_info  # update global dict

        self.update_signal.emit(new_pytest_process_info)
        QCoreApplication.processEvents()
        write_test_status(self.run_guid, self.max_processes, name, new_pytest_process_info)
