from multiprocessing import Process, Queue, Event
from typing import List
import io
import contextlib
from pathlib import Path
import time
from queue import Empty

import pytest
from PySide6.QtCore import QObject, Signal, Slot, QTimer, QCoreApplication
from typeguard import typechecked
from psutil import Process as PsutilProcess
from psutil import NoSuchProcess

from ..logging import get_logger
from ...common import get_guid, PytestResult, PytestProcessState, PytestStatus, PytestProcessMonitorData
from ..preferences import get_pref
from ..test_list import get_tests
from ...db import write_test_status


log = get_logger()


def put_process_monitor_data(_psutil_process: PsutilProcess, queue: Queue):
    try:
        cpu_percent = _psutil_process.cpu_percent()
        memory_percent = _psutil_process.memory_percent()
    except NoSuchProcess:
        cpu_percent = None
        memory_percent = None
    if cpu_percent is not None and memory_percent is not None:
        process_info = PytestProcessMonitorData(pid=_psutil_process.pid, name=_psutil_process.name(), cpu_percent=cpu_percent, memory_percent=memory_percent)
        queue.put(process_info)


class _PytestProcessMonitor(Process):

    def __init__(self, pytest_process_pid: int, update_rate: float, process_monitor_queue: Queue):
        super().__init__()
        self._pytest_process_pid = pytest_process_pid
        self._update_rate = update_rate
        self._psutil_process = None
        self._process_monitor_queue = process_monitor_queue
        self._stop_event = Event()

    def run(self):

        self._psutil_process = PsutilProcess(self._pytest_process_pid)
        self._psutil_process.cpu_percent()  # initialize psutil's CPU usage (ignore the first 0.0)

        while not self._stop_event.is_set():
            # memory percent default is "rss"
            put_process_monitor_data(self._psutil_process, self._process_monitor_queue)
            self._stop_event.wait(self._update_rate)

        # ensure we call PsutilProcess.cpu_percent() at least twice to get a valid CPU percent
        put_process_monitor_data(self._psutil_process, self._process_monitor_queue)

    def request_stop(self):
        self._stop_event.set()


class _PytestProcess(Process):
    """
    A process that performs a pytest run.
    """

    @typechecked()
    def __init__(self, test: Path | str, update_rate: float) -> None:
        """
        :param test: the test to run
        """
        super().__init__(name=str(test))
        self.test = test
        self.update_rate = update_rate
        self.result_queue = Queue()  # results of the pytest run will be sent here
        # process information
        self._process_monitor = None
        self._process_monitor_queue = Queue()

    def run(self) -> None:
        log.info(f"{self.__class__.__name__}:{self.name=} starting")
        self._process_monitor = _PytestProcessMonitor(self.pid, self.update_rate, self._process_monitor_queue)
        self._process_monitor.start()
        buf = io.StringIO()
        # Redirect stdout and stderr so nothing goes to the console
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            exit_code = pytest.main([self.test])
        output: str = buf.getvalue()
        pytest_result = PytestResult(exit_code=exit_code, output=output, time_stamp=time.time())
        self.result_queue.put(pytest_result)
        self._process_monitor.request_stop()
        self._process_monitor.join(100.0)  # plenty of time for the monitor to stop
        if self._process_monitor.is_alive():
            log.error(f"{self._process_monitor} is alive")
        log.info(f"{self.__class__.__name__}{self.name=},{exit_code=},{output=}")

    @typechecked()
    def get_result(self) -> PytestResult | None:
        """
        Returns the result of the pytest run, if available.
        """
        try:
            result = self.result_queue.get(False)
        except Empty:
            result = None
        return result

    def get_pytest_process_monitor_data(self) -> PytestProcessMonitorData:
        """
        Returns the process monitor data, if available.
        """
        monitor_data = None
        max_cpu_percent = 0.0
        max_memory_percent = 0.0
        try:
            while (monitor_data := self._process_monitor_queue.get(False)) is not None:
                max_cpu_percent = max(max_cpu_percent, monitor_data.cpu_percent)
                max_memory_percent = max(max_memory_percent, monitor_data.memory_percent)
                monitor_data = PytestProcessMonitorData(pid=monitor_data.pid, name=monitor_data.name, cpu_percent=max_cpu_percent, memory_percent=max_memory_percent)
        except Empty:
            pass
        return monitor_data


class PytestRunnerWorker(QObject):

    # signals to request pytest actions
    _request_run_signal = Signal(int)  # request run, passing in the number of processes to run
    _request_update_signal = Signal()  # request update
    _request_stop_signal = Signal()  # request stop
    request_exit_signal = Signal()  # request exit (not private since it's connected to the thread quit slot)

    update_signal = Signal(PytestStatus)  # caller connects to this signal to get updates

    @typechecked()
    def request_run(self, run_guid: str, max_processes: int):
        self.run_guid = run_guid
        self._request_run_signal.emit(max_processes)

    def request_update(self):
        self._request_update_signal.emit()

    def request_stop(self):
        self._request_stop_signal.emit()

    def request_exit(self):
        self._scheduler_timer.stop()
        self._scheduler_timer.deleteLater()
        self.request_exit_signal.emit()

    @typechecked()
    def __init__(self, tests: List[str | Path] | None = None) -> None:
        super().__init__()
        self.tests = tests
        self.processes = {}
        self.statuses = {}
        self.starts = {}
        self.ends = {}
        self.max_processes = 1
        self.run_guid = None

        self._request_run_signal.connect(self._run)
        self._request_stop_signal.connect(self._stop)
        self._request_update_signal.connect(self._update)

        self._scheduler_timer = QTimer()
        self._scheduler_timer.timeout.connect(self._scheduler)
        self._scheduler_timer.start(1000)

    @Slot()
    def _run(self, max_processes: int):
        """
        Runs in the background to start and monitor pytest processes.
        """
        log.info(f"{__class__.__name__}.run()")

        pref = get_pref()
        refresh_rate = pref.refresh_rate

        self.run_guid = get_guid()

        self.max_processes = max(max_processes, 1)  # ensure at least one process is run

        if self.processes is None:
            self.processes = {}

        self._stop()  # in case any tests are already running

        if self.tests is None:
            tests = get_tests()
        else:
            tests = self.tests

        self.starts = {}
        self.ends = {}

        for test in tests:
            if test not in self.processes or not self.processes[test].is_alive():
                process = _PytestProcess(test, refresh_rate)
                self.processes[test] = process
                status = PytestStatus(
                    name=test,
                    process_monitor_data=process.get_pytest_process_monitor_data(),
                    state=PytestProcessState.QUEUED,
                    exit_code=None,
                    output=None,
                    start=None,
                    end=None,
                )
                write_test_status(self.run_guid, self.max_processes, test, status, None)
                self.statuses[test] = status
                self.update_signal.emit(status)
                QCoreApplication.processEvents()

    @Slot()
    def _stop(self):

        log.info(f"{__class__.__name__}.stop() - entering")
        for test, process in self.processes.items():
            log.info(f"{process.name=},{process.is_alive()=},{process.pid=},{process.exitcode=}")
            if process.is_alive():
                log.info(f"terminating {test}")
                try:
                    process.terminate()
                except PermissionError:
                    log.warning(f"PermissionError terminating {test}")
                log.info(f"joining {test}")
                try:
                    process.join(100)
                except PermissionError:
                    log.warning(f"PermissionError joining {test}")
                status = PytestStatus(
                    name=test,
                    process_monitor_data=process.get_pytest_process_monitor_data(),
                    state=PytestProcessState.TERMINATED,
                    exit_code=None,
                    output=None,
                    start=self.starts.get(test),
                    end=self.ends.get(test),
                )
                self.statuses[test] = status
        log.info(f"{__class__.__name__}.stop() - exiting")

    @Slot()
    def _update(self):
        # status update (if any status updates are available)
        for test, process in self.processes.items():
            if (result := process.get_result()) is not None:
                if result.exit_code is None:
                    state = PytestProcessState.RUNNING
                else:
                    state = PytestProcessState.FINISHED
                    if test not in self.ends:
                        self.ends[test] = result.time_stamp
                status = PytestStatus(
                    name=test,
                    process_monitor_data=process.get_pytest_process_monitor_data(),
                    state=state,
                    exit_code=result.exit_code,
                    output=result.output,
                    start=self.starts.get(test),
                    end=self.ends.get(test),
                )
                log.info(f"{__class__.__name__}._update():{status=}")
                self.update_signal.emit(status)
                QCoreApplication.processEvents()
                write_test_status(self.run_guid, self.max_processes, test, status, result)

    @Slot()
    def _scheduler(self):

        # determine what tests to run
        number_of_running_processes = len([process for process in self.processes.values() if process.is_alive()])
        max_number_of_tests_to_run = self.max_processes - number_of_running_processes
        tests_to_run = []
        for test in sorted(self.statuses):
            if len(tests_to_run) >= max_number_of_tests_to_run:
                break
            status = self.statuses[test]
            if status.state == PytestProcessState.QUEUED:
                tests_to_run.append(test)
        if len(tests_to_run) > 0:
            log.info(f"{tests_to_run=}")

        # run tests
        for test in tests_to_run:
            log.info(f"{__class__.__name__}: {test} is queued - starting")
            process = self.processes[test]
            if not process.is_alive():
                log.info(f"{__class__.__name__}: starting {test}")
                self.starts[test] = time.time()
                process.start()
            status = PytestStatus(
                name=test,
                process_monitor_data=process.get_pytest_process_monitor_data(),
                state=PytestProcessState.RUNNING,
                exit_code=None,
                output=None,
                start=self.starts[test],
                end=None,
            )
            write_test_status(self.run_guid, self.max_processes, test, status, None)
            log.info(f"{status=}")
            self.statuses[test] = status
            self.update_signal.emit(status)
            QCoreApplication.processEvents()
