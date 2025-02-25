from multiprocessing import Process, Queue
from typing import List
import io
import contextlib
from pathlib import Path
import time
from queue import Empty

import pytest
from PySide6.QtCore import QObject, Signal, Slot, QTimer, QCoreApplication
from typeguard import typechecked

from ..logging import get_logger
from ..model import PytestResult, PytestProcessState, PytestStatus
from ..test_list import get_tests

log = get_logger()


class _PytestProcess(Process):
    """
    A process that performs a pytest run.
    """

    @typechecked()
    def __init__(self, test: Path | str) -> None:
        """
        :param test: the test to run
        """
        super().__init__(name=str(test))
        self.test = test
        self.result_queue = Queue()  # results of the pytest run will be sent here

    def run(self) -> None:
        log.info(f"{self.__class__.__name__}:{self.name=} starting")
        buf = io.StringIO()
        # Redirect stdout and stderr so nothing goes to the console
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            exit_code = pytest.main([self.test])
        output: str = buf.getvalue()
        pytest_result = PytestResult(exit_code=exit_code, output=output)
        self.result_queue.put(pytest_result)
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


class PytestRunnerWorker(QObject):

    # signals to request pytest actions
    _request_run_signal = Signal(int)  # request run, passing in the number of processes to run
    _request_update_signal = Signal()  # request update
    _request_stop_signal = Signal()  # request stop
    request_exit_signal = Signal()  # request exit (not private since it's connected to the thread quit slot)

    update_signal = Signal(PytestStatus)  # caller connects to this signal to get updates

    @typechecked()
    def request_run(self, max_processes: int):
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
        self.max_processes = 1

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

        self.max_processes = max(max_processes, 1)  # ensure at least one process is run

        if self.processes is None:
            self.processes = {}

        self._stop()  # in case any tests are already running

        if self.tests is None:
            tests = get_tests()
        else:
            tests = self.tests

        for test in tests:
            if test not in self.processes or not self.processes[test].is_alive():
                process = _PytestProcess(test)
                self.processes[test] = process
                status = PytestStatus(name=test, state=PytestProcessState.QUEUED, exit_code=None, output=None, time_stamp=time.time())
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
                    process.join(10)
                except PermissionError:
                    log.warning(f"PermissionError joining {test}")
            self.statuses[test] = PytestStatus(name=test, state=PytestProcessState.FINISHED, exit_code=None, output=None, time_stamp=time.time())
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
                status = PytestStatus(name=test, state=state, exit_code=result.exit_code, output=result.output, time_stamp=time.time())
                log.info(f"{__class__.__name__}._update():{status=}")
                self.update_signal.emit(status)
                QCoreApplication.processEvents()

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
                process.start()
            status = PytestStatus(name=test, state=PytestProcessState.RUNNING, exit_code=None, output=None, time_stamp=time.time())
            log.info(f"{status=}")
            self.statuses[test] = status
            self.update_signal.emit(status)
            QCoreApplication.processEvents()
