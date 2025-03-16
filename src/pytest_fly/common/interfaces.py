from dataclasses import dataclass
from enum import StrEnum, auto
import time

from _pytest.config import ExitCode


class PytestProcessState(StrEnum):
    """
    Represents the state of a test process.
    """

    UNKNOWN = auto()  # unknown state
    QUEUED = auto()  # queued to be run by the PyTest runner scheduler
    RUNNING = auto()  # test is currently running
    FINISHED = auto()  # test has finished
    TERMINATED = auto()  # test was terminated


@dataclass
class PytestProcessInfo:
    """
    Information about a running test process, e.g. for the UI.
    """

    name: str  # test name
    state: PytestProcessState  # state of the test process
    pid: int | None = None  # OS process ID of the pytest process
    exit_code: ExitCode | None = None  # exit code of the test
    output: str | None = None  # output (stdout, stderr) of the test
    start: float | None = None  # epoch when the test started (not when queued)
    end: float | None = None  # epoch when the test ended
    cpu_percent: float | None = None  # CPU utilization as a percentage (100.0 = 1 CPU)
    memory_percent: float | None = None  # memory utilization as a percentage (100.0 = 100% of RSS memory)
    time_stamp: float = time.time()  # timestamp when the data was last updated


def exit_code_to_string(exit_code: ExitCode | None) -> str:
    if exit_code is None:
        exit_code_string = str(exit_code)
    else:
        exit_code_string = exit_code.name
    return exit_code_string
