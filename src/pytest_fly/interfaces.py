"""
Core data structures and enumerations shared across the application.

Defines the fundamental types used by the runner, database, and GUI layers:
:class:`ScheduledTest`, :class:`PytestProcessInfo`, :class:`PytestRunnerState`,
:class:`RunMode`, :class:`TestOrder`, and :class:`PyTestFlyExitCode`.
"""

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from functools import total_ordering

from pytest import ExitCode

from .logger import get_logger

log = get_logger()


def _lines_per_second(duration: float, coverage: float) -> float:
    """
    Calculate the line coverage per second.

    Used by :class:`ScheduledTest` ordering to prioritise tests that cover
    the most lines in the least time.

    :param duration: Test duration in seconds.
    :param coverage: Fraction of lines covered (0.0 to 1.0).
    :return: Lines-per-second efficiency metric.
    """

    lines_per_second = coverage / max(duration, 1e-9)  # avoid division by zero
    return lines_per_second


@total_ordering
@dataclass(frozen=True)
class ScheduledTest:
    """
    Represents a test that is scheduled to be run.
    """

    node_id: str  # unique identifier for the test
    singleton: bool  # True if the test is a singleton
    duration: float | None  # duration of the most recent run (seconds)
    coverage: float | None  # coverage of the most recent run, between 0.0 and 1.0 (1.0 = this tests covers all the code)

    def __eq__(self, other):
        """Return True if both tests have the same node_id."""
        if not isinstance(other, ScheduledTest):
            return NotImplemented
        return self.node_id == other.node_id

    def __hash__(self):
        """Hash based on node_id to be consistent with __eq__."""
        return hash(self.node_id)

    def __lt__(self, other):
        """
        Return True if this test should be executed *earlier* than other (i.e. has higher priority).
        """
        if not isinstance(other, ScheduledTest):
            return NotImplemented
        if self.singleton and not other.singleton:
            return False
        elif not self.singleton and other.singleton:
            return True
        elif self.duration is None or self.coverage is None or other.duration is None or other.coverage is None:
            return self.node_id < other.node_id
        else:
            return _lines_per_second(self.duration, self.coverage) > _lines_per_second(other.duration, other.coverage)


class TestOrder(IntEnum):
    PYTEST = 0  # use pytest's default collection order (alphabetical by node_id)
    COVERAGE = 1  # order by coverage efficiency (lines covered per second), falling back to node_id when no prior data


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
    STOPPED = "Stopped"


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
    STOPPED = 102  # test was queued but never ran (soft stop)


@dataclass(frozen=True)
class PutVersionInfo:
    """
    Detected metadata about the program under test (PUT) — the package/project whose tests are being run.

    Captured once at the start of each pytest-fly run and stamped onto every
    :class:`PytestProcessInfo` record via its ``put_version`` / ``put_fingerprint``
    scalar fields.  Used to label runs in the GUI and to gate :attr:`RunMode.CHECK`.
    """

    name: str | None  # PEP 621 project name, or None if undetectable
    version: str | None  # declared or installed version, or None
    source: str  # "pyproject" | "setup.cfg" | "importlib.metadata" | "override" | "unknown"
    git_describe: str | None  # e.g. "v0.3.19-4-gabc1234-dirty"
    git_sha: str | None  # short SHA (7 chars)
    git_branch: str | None
    git_dirty: bool | None  # True if working tree has uncommitted changes
    project_root: str  # absolute path used for detection
    author: str | None = None  # first author listed in pyproject.toml or setup.cfg, if any

    def fingerprint(self) -> str:
        """Stable string for equality comparison in :attr:`RunMode.CHECK`.

        Includes ``git_dirty`` so any uncommitted change invalidates CHECK and
        falls back to a full restart.
        """
        parts = [
            self.name or "",
            self.version or "",
            self.source,
            self.git_sha or "",
            "dirty" if self.git_dirty else "clean" if self.git_dirty is False else "",
        ]
        return "|".join(parts)

    def short_label(self) -> str:
        """Concise display label for the status window header (e.g. ``"pytest-fly 0.3.19 (abc1234-dirty)"``)."""
        name = self.name or "unknown"
        version = self.version or "?"
        label = f"{name} {version}"
        if self.git_sha:
            suffix = self.git_sha
            if self.git_dirty:
                suffix += "-dirty"
            label += f" ({suffix})"
        elif self.git_dirty:
            label += " (dirty)"
        return label


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
    cpu_percent: float | None = None  # peak CPU usage during the run, as reported by psutil (100.0 = one full logical CPU; can exceed 100 on multi-core)
    memory_percent: float | None = None  # peak memory usage during the run (percent of total physical RAM)
    put_version: str | None = None  # program-under-test short label (e.g. "pytest-fly 0.3.19 (abc1234)")
    put_fingerprint: str | None = None  # program-under-test fingerprint for RunMode.CHECK comparison
