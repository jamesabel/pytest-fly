from dataclasses import dataclass
from enum import StrEnum, auto

from _pytest.config import ExitCode


@dataclass(frozen=True)
class PytestResult:
    """
    Represents the result of a pytest run.
    """

    exit_code: ExitCode
    output: str  # stdout/stderr output


class PytestProcessState(StrEnum):
    """
    Represents the state of a test process.
    """

    UNKNOWN = auto()  # unknown state
    QUEUED = auto()  # queued to be run by the PyTest runner scheduler
    RUNNING = auto()  # test is currently running
    FINISHED = auto()  # test has finished
    TERMINATED = auto()  # test was terminated

    def __str__(self):
        return self.name


@dataclass(frozen=True)
class PytestStatus:
    """
    Represents the status of a test process.
    """

    name: str  # test name
    state: PytestProcessState
    exit_code: ExitCode | None  # None if running, ExitCode if finished
    output: str | None  # stdout/stderr output
    time_stamp: float  # epoch timestamp of this status
