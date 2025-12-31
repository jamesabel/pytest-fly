from dataclasses import dataclass
from enum import IntEnum

from pytest import ExitCode
from balsa import get_logger

from .__version__ import application_name
from .pytest_runner.const import PytestProcessState

log = get_logger(application_name)


def _lines_per_second(duration: float, coverage: float) -> float:
    """
    Calculate the line coverage per second.
    """

    lines_per_second = coverage / max(duration, 1e-9)  # avoid division by zero
    return lines_per_second


@dataclass(frozen=True)
class ScheduledTest:
    """
    Represents a test that is scheduled to be run.
    """

    node_id: str  # unique identifier for the test
    singleton: bool  # True if the test is a singleton
    duration: float | None  # duration of the most recent run (seconds)
    coverage: float | None  # coverage of the most recent run, between 0.0 and 1.0 (1.0 = this tests covers all the code)

    def __gt__(self, other):
        """
        Compare two ScheduledTest objects. True if this object should be executed earlier than the other.
        """
        if self.singleton and not other.singleton:
            gt = True  # this object is a singleton, but the other is not, so this object should be executed later
        elif not self.singleton and other.singleton:
            gt = False  # this object is not a singleton, but the other is, so this object should be executed earlier
        elif self.duration is None or self.coverage is None or other.duration is None or other.coverage is None:
            # if either test has no duration or coverage, we just sort alphabetically
            gt = self.node_id > other.node_id
        else:
            # the test with the most effective coverage per second should be executed first
            gt = _lines_per_second(self.duration, self.coverage) > _lines_per_second(other.duration, other.coverage)
        return gt

    def __eq__(self, other):
        """
        Compare two ScheduledTest objects.
        """
        eq = self.singleton == other.singleton and self.duration == other.duration and self.coverage == other.coverage
        return eq


class ScheduledTests:
    """
    Represents a list of scheduled tests.
    """

    def __init__(self) -> None:
        self._tests_set = set()
        self._is_sorted = True
        self.tests = []  # list of scheduled (sorted) tests

    def add(self, test: ScheduledTest) -> None:
        """
        Add a test to the list of scheduled tests. (not called append since we'll sort later in the schedule method)
        """
        self._is_sorted = False  # mark the list as unsorted so we can sort it later
        self._tests_set.add(test)

    def schedule(self):
        """
        Put the test in order so they will run in scheduled order.
        """
        if not self._is_sorted:
            self.tests = sorted(self._tests_set)
            self._is_sorted = True

    def __iter__(self):
        """
        Iterate over the scheduled tests.
        """
        self.schedule()  # sort the tests before iterating
        return iter(self.tests)

    def __len__(self) -> int:
        """
        Get the number of scheduled tests.
        """
        return len(self.tests)


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


int_to_exit_code = {exit_code.value: exit_code for exit_code in ExitCode}


def exit_code_to_string(exit_code: ExitCode | int | None) -> str:
    if isinstance(exit_code, int):
        exit_code = int_to_exit_code[exit_code]
    if isinstance(exit_code, ExitCode):
        exit_code_string = exit_code.name
    else:
        exit_code_string = "running"
    return exit_code_string


@dataclass(frozen=True)
class PytestProcessInfo:
    """
    Information about a pytest process.
    """

    run_guid: str  # the pytest run GUID this process is associated with
    name: str  # process name (usually the test name)
    pid: int | None  # process ID from the OS (if None the process has not started yet)
    exit_code: ExitCode | None  # exit code from pytest, None if the test is still running
    output: str | None  # output from the pytest run, None if the test is still running
    time_stamp: float  # time stamp of the info update
