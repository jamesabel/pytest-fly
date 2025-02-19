from multiprocessing import Process, Queue
from typing import List
import io
import contextlib
from dataclasses import dataclass
from pathlib import Path
import time

import pytest
from pytest import ExitCode
from PySide6.QtCore import QObject, Signal, Slot
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
    def get_result(self) -> _PytestResult:
        return self.result_queue.get()


@dataclass(frozen=True)
class PytestStatus:
    name: str
    running: bool
    exit_code: ExitCode | None
    output: str | None
    time_stamp: float


class PytestRunnerWorker(QObject):

    update = Signal(PytestStatus)
    finished = Signal()  # use to quit the thread this worker is moved to

    @typechecked()
    def __init__(self, tests: List[str | Path] | None = None) -> None:
        super().__init__()
        self.tests = tests
        self.statuses = []

    @Slot()
    def run(self):
        if self.tests is None:
            self.tests = get_tests()
        for test in self.tests:
            pytest_process = _PytestProcess(test)
            pytest_process.start()
            status = PytestStatus(name=test, running=True, exit_code=None, output=None, time_stamp=time.time())
            self.update.emit(status)
            while pytest_process.is_alive():
                pytest_process.join(1)
            result = pytest_process.get_result()
            status = PytestStatus(name=test, running=False, exit_code=result.exit_code, output=result.output, time_stamp=time.time())
            self.update.emit(status)
        self.finished.emit()
