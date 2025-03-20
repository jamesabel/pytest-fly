from dataclasses import dataclass
from enum import StrEnum, auto, IntEnum
import time
from typing import Iterable

from pytest import ExitCode
from balsa import get_logger
from ..__version__ import application_name

log = get_logger(application_name)


class RunMode(IntEnum):
    RESTART = 0  # rerun all tests
    RESUME = 1  # resume test run, and run tests that either failed or were not run
    CHECK = 2  # resume if program under test has not changed, otherwise restart


@dataclass
class RunParameters:
    """
    Parameters provided to the pytest runner.
    """

    run_guid: str  # unique identifier for the run
    run_mode: RunMode  # True to automatically determine the number of processes to run in parallel
    max_processes: int  # maximum number of processes to run in parallel (ignored if dynamic_processes is True)


class PytestProcessState(StrEnum):
    """
    Represents the state of a test process.
    """

    UNKNOWN = auto()  # unknown state
    QUEUED = auto()  # queued to be run by the scheduler
    RUNNING = auto()  # test is currently running
    FINISHED = auto()  # test has finished
    TERMINATED = auto()  # test was terminated


def state_order(pytest_process_state: PytestProcessState) -> int:
    # for sorting PytestProcessState, but keeping PytestProcessState as a str
    orders = {PytestProcessState.UNKNOWN: 0, PytestProcessState.QUEUED: 1, PytestProcessState.RUNNING: 2, PytestProcessState.FINISHED: 3, PytestProcessState.TERMINATED: 4}
    if pytest_process_state is None:
        order = orders[PytestProcessState.UNKNOWN]
    else:
        order = orders[pytest_process_state]
    return order


@dataclass
class PytestProcessInfo:
    """
    Information about a running test process, e.g. for the UI.
    """

    name: str  # test name
    state: PytestProcessState | None = None  # state of the test process
    pid: int | None = None  # OS process ID of the pytest process
    exit_code: ExitCode | None = None  # exit code of the test
    output: str | None = None  # output (stdout, stderr) of the test
    start: float | None = None  # epoch when the test started (not when queued)
    end: float | None = None  # epoch when the test ended
    cpu_percent: float | None = None  # CPU utilization as a percentage (100.0 = 1 CPU)
    memory_percent: float | None = None  # memory utilization as a percentage (100.0 = 100% of RSS memory)
    time_stamp: float = time.time()  # timestamp when the data was last updated


# create a PytestProcessInfo from iterable
def pytest_process_info_from_iterable(t: Iterable) -> PytestProcessInfo:
    pytest_process_info = PytestProcessInfo(*t)
    return pytest_process_info


int_to_exit_code = {exit_code.value: exit_code for exit_code in ExitCode}


def exit_code_to_string(exit_code: ExitCode | int | None) -> str:
    if isinstance(exit_code, int):
        exit_code = int_to_exit_code[exit_code]
    if isinstance(exit_code, ExitCode):
        exit_code_string = exit_code.name
    else:
        exit_code_string = "unknown"
    return exit_code_string
