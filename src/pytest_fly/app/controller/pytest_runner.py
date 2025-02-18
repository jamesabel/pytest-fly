from multiprocessing import Process, Queue
from typing import List
from queue import Empty
import io
import contextlib
from dataclasses import dataclass
from pathlib import Path
import time

import pytest
from pytest import ExitCode
from PySide6.QtCore import QThread, QObject, Signal, Slot
from typeguard import typechecked

from ..logging import get_logger

log = get_logger()


@dataclass(frozen=True)
class _PytestResult:
    exit_code: ExitCode
    output: str


class _PytestProcess(Process):

    @typechecked()
    def __init__(self, process_name: str, test_path: Path) -> None:
        super().__init__(name=process_name)
        self.test_path = test_path
        self.result_queue = Queue()

    def run(self) -> None:
        buf = io.StringIO()
        # Redirect stdout and stderr so nothing goes to the console
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            exit_code = pytest.main([str(self.test_path)])
        output: str = buf.getvalue()
        pytest_result = _PytestResult(exit_code=exit_code, output=output)
        self.result_queue.put(pytest_result)

    @typechecked()
    def get_result(self) -> _PytestResult:
        return self.result_queue.get()


@dataclass(frozen=True)
class PytestStatus:
    name: Path
    running: bool
    exit_code: ExitCode | None
    output: str | None
    time_stamp: float


class PytestRunnerWorker(QObject):

    update = Signal(PytestStatus)
    finished = Signal()  # use to quit the thread this worker is moved to

    def __init__(self, test_paths: List[Path]):
        super().__init__()
        self.test_paths = test_paths
        self.statuses = []

    @Slot()
    def run(self):
        for test_path in self.test_paths:
            pytest_process = _PytestProcess(test_path.name, test_path)
            pytest_process.start()
            status = PytestStatus(name=test_path, running=True, exit_code=None, output=None, time_stamp=time.time())
            self.update.emit(status)
            while pytest_process.is_alive():
                pytest_process.join(1)
            result = pytest_process.get_result()
            status = PytestStatus(name=test_path, running=False, exit_code=result.exit_code, output=result.output, time_stamp=time.time())
            self.update.emit(status)
        self.finished.emit()
