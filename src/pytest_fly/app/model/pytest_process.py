from dataclasses import dataclass
from enum import StrEnum, auto

from pytest import ExitCode


def exit_code_to_string(exit_code: ExitCode | None) -> str:
    if exit_code is None:
        exit_code_string = str(exit_code)
    else:
        exit_code_string = exit_code.name
    return exit_code_string


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

    QUEUED = auto()  # queued to be run by the PyTest runner scheduler
    RUNNING = auto()  # test is currently running
    FINISHED = auto()  # test has finished

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


@dataclass(frozen=True)
class PytestKey:
    """
    Represents a unique key for a test and state.
    """

    name: str
    state: PytestProcessState
