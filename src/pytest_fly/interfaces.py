from dataclasses import dataclass
from enum import IntEnum, StrEnum

from pytest import ExitCode
from balsa import get_logger

from .__version__ import application_name


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


class RunMode(IntEnum):
    RESTART = 0  # rerun all tests
    RESUME = 1  # resume test run, and run tests that either failed or were not run
    CHECK = 2  # resume if program under test has not changed, otherwise restart


class PytestRunnerState(StrEnum):
    QUEUED = "Queued"
    RUNNING = "Running"
    PASS = "Pass"
    FAIL = "Fail"
    TERMINATED = "Terminated"


class PyTestFlyExitCode(IntEnum):

    # pytest exit codes
    OK = ExitCode.OK
    TESTS_FAILED = ExitCode.TESTS_FAILED
    INTERRUPTED = ExitCode.INTERRUPTED
    INTERNAL_ERROR = ExitCode.INTERNAL_ERROR
    USAGE_ERROR = ExitCode.USAGE_ERROR
    NO_TESTS_COLLECTED = ExitCode.NO_TESTS_COLLECTED
    assert len(ExitCode) == 6  # Number of entries above. Check in case PyTest adds more exit codes.
    MAX_PYTEST_EXIT_CODE = max(item.value for item in ExitCode)

    # pytest-fly specific exit codes
    NONE = 100  # not yet set
    TERMINATED = 101  # test run was forcefully terminated


@dataclass(frozen=True)
class PytestProcessInfo:
    """
    Information about a pytest process.
    """

    run_guid: str  # the pytest run GUID this process is associated with
    name: str  # process name (usually the test name)
    pid: int | None  # process ID from the OS (if None the process has not started yet)
    exit_code: PyTestFlyExitCode | ExitCode
    output: str | None  # output from the pytest run, None if the test is still running
    time_stamp: float  # time stamp of the info update
