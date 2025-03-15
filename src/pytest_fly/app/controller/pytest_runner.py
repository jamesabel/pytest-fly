from multiprocessing import Process, Queue, Event, Manager, Lock
import io
import contextlib
from pathlib import Path
from queue import Empty
import time

import psutil
import pytest
from PySide6.QtCore import QObject, Signal, Slot, QTimer, QCoreApplication
from numpy.f2py.crackfortran import endifs
from typeguard import typechecked
from psutil import Process as PsutilProcess
from psutil import NoSuchProcess

from ..logging import get_logger
from ...common import get_guid, PytestProcessInfo, PytestProcessState
from ..preferences import get_pref
from ..test_list import get_tests
from ...db import write_test_status


log = get_logger()




def put_process_monitor_data(name: str, psutil_process: PsutilProcess, queue: Queue):
    if psutil_process.is_running():
        pid = psutil_process.pid
        try:
            cpu_percent = psutil_process.cpu_percent()
            memory_percent = psutil_process.memory_percent()
        except NoSuchProcess:
            cpu_percent = None
            memory_percent = None
        if cpu_percent is not None and memory_percent is not None:
            pytest_process_info = PytestProcessInfo(name, PytestProcessState.RUNNING, pid, cpu_percent=cpu_percent, memory_percent=memory_percent)
            queue.put(pytest_process_info)


class _PytestProcessMonitor(Process):

    def __init__(self, name: str, pid: int, update_rate: float, process_monitor_queue: Queue):
        super().__init__()
        self._name = name
        self._pid = pid
        self._update_rate = update_rate
        self._psutil_process = None
        self._process_monitor_queue = process_monitor_queue
        self._stop_event = Event()

    def run(self):

        self._psutil_process = PsutilProcess(self._pid)
        self._psutil_process.cpu_percent()  # initialize psutil's CPU usage (ignore the first 0.0)

        while not self._stop_event.is_set():
            # memory percent default is "rss"
            put_process_monitor_data(self._name, self._psutil_process, self._process_monitor_queue)
            self._stop_event.wait(self._update_rate)

        # ensure we call PsutilProcess.cpu_percent() at least twice to get a valid CPU percent
        put_process_monitor_data(self._name, self._psutil_process, self._process_monitor_queue)

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
        pytest_process_info = PytestProcessInfo(self.name, PytestProcessState.RUNNING, self.pid)
        self.pytest_monitor_queue.put(pytest_process_info)

        # Finally, actually run pytest!
        # Redirect stdout and stderr so nothing goes to the console.
        start = time.time()
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
        pytest_process_info = PytestProcessInfo(self.name, PytestProcessState.FINISHED, self.pid, exit_code, output, start, end)
        self.pytest_monitor_queue.put(pytest_process_info)

        log.debug(f"{self.name=},{self.name},{exit_code=},{output=}")

    # @typechecked()
    # def get_result(self) -> PytestProcessInfo | None:
    #     """
    #     Returns the result of the pytest run, if available.
    #     """
    #     try:
    #         result = self._result_queue.get(False)
    #     except Empty:
    #         result = None
    #     return result

    # def get_pytest_process_monitor_data(self) -> PytestProcessInfo:
    #     """
    #     Returns the process monitor data, if available.
    #     """
    #     monitor_data = None
    #     max_cpu_percent = 0.0
    #     max_memory_percent = 0.0
    #     try:
    #         while (monitor_data := self._process_monitor_queue.get(False)) is not None:
    #             max_cpu_percent = max(max_cpu_percent, monitor_data.cpu_percent)
    #             max_memory_percent = max(max_memory_percent, monitor_data.memory_percent)
    #             monitor_data = PytestProcessInfo(monitor_data.name, monitor_data.pid, cpu_percent=max_cpu_percent, memory_percent=max_memory_percent)
    #     except Empty:
    #         pass
    #     return monitor_data


class PytestRunnerWorker(QObject):

    # signals to request pytest actions
    _request_run_signal = Signal(int)  # request run, passing in the number of processes to run
    _request_stop_signal = Signal()  # request stop
    request_exit_signal = Signal()  # request exit (not private since it's connected to the thread quit slot)

    update_signal = Signal(PytestProcessInfo)  # caller connects to this signal to get updates (e.g., for the GUI)

    @typechecked()
    def request_run(self, run_guid: str, max_processes: int):
        self.run_guid = run_guid
        self._request_run_signal.emit(max_processes)

    def request_stop(self):
        self._request_stop_signal.emit()

    def request_exit(self):
        self._scheduler_timer.stop()
        self._scheduler_timer.deleteLater()
        self.request_exit_signal.emit()

    @typechecked()
    def __init__(self, tests: list[str] | None = None) -> None:
        super().__init__()

        if tests is None:
            self.tests = get_tests()
        else:
            self.tests = tests

        self.test_queue = Queue()  # tests to be run
        self.pytest_monitor_queue = Queue()  # monitor data for the pytest processes

        self.pytest_processes_manager = Manager()  # dict values are PytestProcessInfo
        self.pytest_processes_dict = self.pytest_processes_manager.dict()

        self._processes = {}

        self.max_processes = 1
        self.run_guid = None

        self._request_run_signal.connect(self._run)
        self._request_stop_signal.connect(self._stop)

        self._scheduler_timer = QTimer()
        self._scheduler_timer.timeout.connect(self._scheduler)
        self._scheduler_timer.start(1000)

    @Slot()
    def _run(self, max_processes: int):
        log.info(f"{max_processes=}")

        self.run_guid = get_guid()

        self.max_processes = max(max_processes, 1)  # ensure at least one process is run

        self._stop()  # in case any tests are already running

        for test in self.tests:
            pytest_process_info = PytestProcessInfo(name=test, state=PytestProcessState.QUEUED)
            self.update_pytest_process_info(pytest_process_info)
            self.test_queue.put(test)

    @Slot()
    def _stop(self):

        for test, pytest_process in self.pytest_processes_dict.items():
            if pytest_process.state == PytestProcessState.RUNNING:
                process = psutil.Process(pytest_process.pid)
                log.info(f"terminating {test}")
                try:
                    process.terminate()
                except PermissionError:
                    log.warning(f"PermissionError terminating {test}")
                log.info(f"joining {test}")
                try:
                    process.wait(100)
                except PermissionError:
                    log.warning(f"PermissionError joining {test}")
                pytest_process_info = PytestProcessInfo(name=test, state=PytestProcessState.TERMINATED)
                self.update_pytest_process_info(pytest_process_info)
        log.info(f"{__class__.__name__}.stop() - exiting")

    # @Slot()
    # def _update(self):
    #     # status update (if any status updates are available)
    #     for test in sorted(self.pytest_processes):
    #         pytest_process = self.pytest_processes[test]
    #         self.update_signal.emit(pytest_process)
    #         QCoreApplication.processEvents()
    #         write_test_status(self.run_guid, self.max_processes, test, pytest_process)

    @Slot()
    def _scheduler(self):

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
                self.update_pytest_process_info(pytest_process_info)

                # we don't generally access self.processes, but we need to keep a reference to the process and ensure it stays alive
                self._processes[test] = _PytestProcess(test, refresh_rate, self.pytest_monitor_queue)
                self._processes[test].start()

        # update UI
        try:
            while (pytest_process_info := self.pytest_monitor_queue.get(False)) is not None:
                self.update_pytest_process_info(pytest_process_info)
        except Empty:
            pass

    def update_pytest_process_info(self, updated_pytest_process_info: PytestProcessInfo):
        name = updated_pytest_process_info.name

        if name in self.pytest_processes_dict:
            # update existing test info
            new_pytest_process_info = self.pytest_processes_dict[name]
            for attribute in updated_pytest_process_info.__dataclass_fields__.keys():  # update the attributes
                if (value := getattr(updated_pytest_process_info, attribute)) is not None:
                    setattr(new_pytest_process_info, attribute, value)
        else:
            # new test (e.g., when queued)
            new_pytest_process_info = updated_pytest_process_info

        with Lock():
            self.pytest_processes_dict[name] = new_pytest_process_info  # update global dict

        self.update_signal.emit(new_pytest_process_info)
        QCoreApplication.processEvents()
        write_test_status(self.run_guid, self.max_processes, name, new_pytest_process_info)
