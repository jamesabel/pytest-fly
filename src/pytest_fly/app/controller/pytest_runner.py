from multiprocessing import Process, Queue
from typing import List
import io
import contextlib
from dataclasses import dataclass
from pathlib import Path
import time
from queue import Empty
from enum import StrEnum, auto

import pytest
from pytest import ExitCode
from PySide6.QtCore import QObject, Signal, Slot, QCoreApplication, QEventLoop
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
        super().__init__(name=str(test))
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
    name: str
    running: bool
    exit_code: ExitCode | None
    output: str | None
    time_stamp: float


class RunnerWorkerState(StrEnum):
    run_requested = auto()
    running = auto()
    stop_requested = auto()
    stopped = auto()
    exit_requested = auto()


class PytestRunnerWorker(QObject):

    request_run_signal = Signal()  # request run
    request_stop_signal = Signal()  # request stop
    request_exit_signal = Signal()  # request exit

    update_signal = Signal(PytestStatus)  # caller connects to this signal to get updates

    @typechecked()
    def __init__(self, tests: List[str | Path] | None = None) -> None:
        super().__init__()
        self.tests = tests
        self.processes = {}
        self.runner_worker_state = RunnerWorkerState.stopped

        self.request_run_signal.connect(self.request_run)
        self.request_stop_signal.connect(self.request_stop)
        self.request_exit_signal.connect(self.request_exit)

        self.run_requested_pending = False
        self.stop_requested_pending = False

    @Slot()
    def request_run(self):
        self.runner_worker_state = RunnerWorkerState.run_requested

    @Slot()
    def request_stop(self):
        self.runner_worker_state = RunnerWorkerState.stop_requested

    @Slot()
    def run(self):
        """
        Runs in the background to start and monitor pytest processes.
        """
        log.info(f"starting {__class__.__name__}")
        while self.runner_worker_state != RunnerWorkerState.exit_requested or any(process.is_alive() for process in self.processes.values()):

            QCoreApplication.processEvents(QEventLoop.WaitForMoreEvents, 1000)  # loop every second, unless there is an event

            if self.runner_worker_state == RunnerWorkerState.run_requested:
                if self.tests is None:
                    self.tests = get_tests()
                for test in self.tests:

                    process = _PytestProcess(test)
                    log.info(f"starting {test}")
                    process.start()
                    self.processes[test] = process

                    starting_status = PytestStatus(name=test, running=True, exit_code=None, output=None, time_stamp=time.time())
                    self.update_signal.emit(starting_status)

                self.runner_worker_state = RunnerWorkerState.running
            elif self.runner_worker_state == RunnerWorkerState.stop_requested:
                for test, process in self.processes.items():
                    log.debug(f"{process.name=},{process.is_alive()=},{process.pid=},{process.exitcode=}")
                    while process.is_alive():
                        log.info(f"terminating {test}")
                        try:
                            process.terminate()
                        except PermissionError:
                            ...
                        process.join(1)
                self.runner_worker_state = RunnerWorkerState.stopped

            # status update (if any status updates are available)
            for test, process in self.processes.items():
                if (result := process.get_result()) is not None:
                    status = PytestStatus(name=test, running=process.is_alive(), exit_code=result.exit_code, output=result.output, time_stamp=time.time())
                    log.info(f"{status=}")
                    self.update_signal.emit(status)

        log.info(f"exiting {__class__.__name__} ({len(self.tests)} tests)")

    @Slot()
    def request_exit(self):
        log.info(f"requesting {__class__.__name__} exit")
        self.runner_worker_state = RunnerWorkerState.exit_requested
        QCoreApplication.processEvents()
