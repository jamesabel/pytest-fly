from multiprocessing import Process, Queue
from queue import Empty
import io
import contextlib
from dataclasses import dataclass
from enum import StrEnum, auto
from pathlib import Path
import time

import pytest
from PySide6.QtCore import QThread
from typeguard import typechecked

from ..logging import get_logger

log = get_logger()


@dataclass(frozen=True)
class _PytestResult:
    return_code: int
    output: str


class _PytestProcess(Process):

    @typechecked()
    def __init__(self, test_path: Path) -> None:
        super().__init__()
        self.test_path = test_path
        self.result_queue = Queue()

    def run(self) -> None:
        buf = io.StringIO()
        # Redirect stdout and stderr so nothing goes to the console
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            return_code: int = pytest.main([str(self.test_path)])
        output: str = buf.getvalue()
        pytest_result = _PytestResult(return_code=return_code, output=output)
        self.result_queue.put(pytest_result)

    @typechecked()
    def get_result(self) -> _PytestResult:
        return self.result_queue.get()


class PytestState(StrEnum):
    START = auto()
    PASS = auto()
    FAIL = auto()


@dataclass(frozen=True)
class PytestStatus:
    name: Path
    state: PytestState
    output: str | None
    time_stamp: float


class PytestRunner(QThread):

    @typechecked()
    def __init__(self, test_paths: list[Path]):
        super().__init__()
        self.test_paths = test_paths
        self.status_queue = Queue()
        self.statuses = []

    def run(self):
        for test_path in self.test_paths:
            # run a test using pytest
            self.status_queue.put(PytestStatus(name=test_path, state=PytestState.START, output=None, time_stamp=time.time()))
            pytest_process = _PytestProcess(test_path)
            pytest_process.start()
            while pytest_process.is_alive():
                pytest_process.join()
            result = pytest_process.get_result()
            if result.return_code == 0:
                self.status_queue.put(PytestStatus(name=test_path, state=PytestState.PASS, output=result.output, time_stamp=time.time()))
            else:
                self.status_queue.put(PytestStatus(name=test_path, state=PytestState.FAIL, output=result.output, time_stamp=time.time()))

    def get_statuses(self) -> list[PytestStatus]:

        # first, update status
        try:
            while (status := self.status_queue.get(block=False)) is not None:
                self.statuses.append(status)
        except Empty:
            pass
        return self.statuses
