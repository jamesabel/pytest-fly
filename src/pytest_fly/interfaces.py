"""
Core data structures and enumerations shared across the application.

Defines the fundamental types used by the runner, database, and GUI layers:
:class:`ScheduledTest`, :class:`PytestProcessInfo`, :class:`PytestRunnerState`,
:class:`RunMode`, :class:`OrderingAspect`, and :class:`PyTestFlyExitCode`.
"""

from dataclasses import dataclass
from enum import IntEnum, StrEnum

from pytest import ExitCode

from .logger import get_logger

log = get_logger()


def lines_per_second(duration: float | None, coverage: float | None) -> float | None:
    """Lines-per-second efficiency metric used by the COVERAGE_EFFICIENCY ordering aspect.

    Returns ``None`` when either input is missing so callers can order
    missing-data tests after the ones with real measurements.
    """
    if duration is None or coverage is None:
        return None
    return coverage / max(duration, 1e-9)  # avoid division by zero


@dataclass(frozen=True)
class ScheduledTest:
    """
    Represents a test that is scheduled to be run.
    """

    node_id: str  # unique identifier for the test
    singleton: bool  # True if the test is a singleton
    duration: float | None  # duration of the most recent passing run (seconds)
    coverage: float | None  # coverage of the most recent run, between 0.0 and 1.0 (1.0 = this tests covers all the code)

    def __eq__(self, other):
        """Return True if both tests have the same node_id."""
        if not isinstance(other, ScheduledTest):
            return NotImplemented
        return self.node_id == other.node_id

    def __hash__(self):
        """Hash based on node_id to be consistent with __eq__."""
        return hash(self.node_id)


class OrderingAspect(StrEnum):
    """An aspect that contributes to the execution order of scheduled tests.

    The Configuration tab exposes these as a reorderable list: each aspect can
    be individually enabled/disabled, and their position in the list sets
    priority (index 0 = highest priority).  ``singleton`` tests are always
    sorted last, regardless of enabled aspects.
    """

    FAILED_FIRST = "failed_first"  # tests that failed in the previous run run first
    NEVER_RUN_FIRST = "never_run_first"  # tests with no DB record (any PUT version) run first
    LONGEST_PRIOR_FIRST = "longest_prior_first"  # tests with the longest prior passing run run first (shrinks parallel critical path)
    COVERAGE_EFFICIENCY = "coverage_efficiency"  # tests with the highest lines-covered-per-second run first


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
