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
    exit_code: ExitCode
    output: str


class PytestProcessState(StrEnum):
    QUEUED = auto()
    RUNNING = auto()
    FINISHED = auto()

    def __str__(self):
        return self.name


@dataclass(frozen=True)
class PytestStatus:
    name: str  # test name
    state: PytestProcessState
    exit_code: ExitCode | None  # None if running, ExitCode if finished
    output: str | None  # stdout/stderr output
    time_stamp: float  # epoch timestamp of this status
