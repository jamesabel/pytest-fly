from multiprocessing import Process, Queue
from typing import List
import io
import contextlib
from dataclasses import dataclass
from pathlib import Path
import time
from queue import Empty

import pytest
from pytest import ExitCode
from PySide6.QtCore import QObject, Signal, Slot, QCoreApplication
from typeguard import typechecked

from ..logging import get_logger
from ..test_list import get_tests

log = get_logger()


@dataclass(frozen=True)
class _PytestResult:
    exit_code: ExitCode
    output: str


class _PytestProcess(Process):

    @typechecked()
    def __init__(self, test: Path | str | None = None) -> None:
        super().__init__(name=str(test), daemon=True)  # daemon since we explicitly terminate the process
        self.test = test
        self.result_queue = Queue()

    def run(self) -> None:
        buf = io.StringIO()
        # Redirect stdout and stderr so nothing goes to the console
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            if self.test is None:
                exit_code = pytest.main()
            else:
                exit_code = pytest.main([self.test])
        output: str = buf.getvalue()
        pytest_result = _PytestResult(exit_code=exit_code, output=output)
        self.result_queue.put(pytest_result)

    @typechecked()
    def get_result(self) -> _PytestResult | None:
        try:
            result = self.result_queue.get(False)
        except Empty:
            result = None
        return result


@dataclass(frozen=True)
class PytestStatus:
    name: str  # test name
    running: bool  # True when running, False when finished
    exit_code: ExitCode | None  # None if running, ExitCode if finished
    output: str | None  # stdout/stderr output
    time_stamp: float  # epoch timestamp of this status


class PytestRunnerWorker(QObject):

    # signals to request pytest actions
    _request_run_signal = Signal()  # request run
    _request_update_signal = Signal()  # request update
    _request_stop_signal = Signal()  # request stop
    request_exit_signal = Signal()  # request exit (not private since it's connected to the thread quit slot)

    update_signal = Signal(PytestStatus)  # caller connects to this signal to get updates

    def request_run(self):
        self._request_run_signal.emit()

    def request_update(self):
        self._request_update_signal.emit()

    def request_stop(self):
        self._request_stop_signal.emit()

    def request_exit(self):
        self.request_exit_signal.emit()

    @typechecked()
    def __init__(self, tests: List[str | Path] | None = None) -> None:
        super().__init__()
        self.tests = tests
        self.processes = None

        self._request_run_signal.connect(self._run)
        self._request_stop_signal.connect(self._stop)
        self._request_update_signal.connect(self._update)

    @Slot()
    def _run(self):
        """
        Runs in the background to start and monitor pytest processes.
        """
        log.info(f"{__class__.__name__}.run()")

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
                log.info(f"starting {test}")
                process.start()
                self.processes[test] = process

                starting_status = PytestStatus(name=test, running=True, exit_code=None, output=None, time_stamp=time.time())
                self.update_signal.emit(starting_status)

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
            QCoreApplication.processEvents()
        QCoreApplication.processEvents()
        log.info(f"{__class__.__name__}.stop() - exiting")

    @Slot()
    def _update(self):
        # status update (if any status updates are available)
        for test, process in self.processes.items():
            if (result := process.get_result()) is not None:
                status = PytestStatus(name=test, running=process.is_alive(), exit_code=result.exit_code, output=result.output, time_stamp=time.time())
                log.info(f"{status=}")
                self.update_signal.emit(status)
