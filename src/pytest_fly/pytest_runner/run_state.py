"""
Run-state classification — maps :class:`PytestProcessInfo` DB records to display states.

This is the single place that turns exit codes into :class:`PytestRunnerState` values and
decides which states are *terminal* (the run-completion rule used by the runner, the stall
watchdog, and the GUI). Kept free of Qt so the runner package stays headless; the GUI maps
states to colors via :mod:`pytest_fly.colors`.
"""

from typeguard import typechecked

from ..interfaces import PyTestFlyExitCode, PytestProcessInfo, PytestRunnerState
from ..logger import get_logger

log = get_logger()

# States that mean "this test is finished" — the state-level twin of
# interfaces.is_terminal_exit_code (a state is terminal iff its exit code is not NONE).
TERMINAL_STATES = frozenset({PytestRunnerState.PASS, PytestRunnerState.FAIL, PytestRunnerState.TERMINATED, PytestRunnerState.STOPPED})


def state_of(info: PytestProcessInfo) -> PytestRunnerState:
    """Classify a single (latest) record into a :class:`PytestRunnerState`."""
    exit_code = info.exit_code
    if exit_code == PyTestFlyExitCode.OK:
        return PytestRunnerState.PASS
    if PyTestFlyExitCode.OK < exit_code <= PyTestFlyExitCode.MAX_PYTEST_EXIT_CODE:
        # any pytest exit code other than OK is a failure
        return PytestRunnerState.FAIL
    if exit_code == PyTestFlyExitCode.TERMINATED:
        return PytestRunnerState.TERMINATED
    if exit_code == PyTestFlyExitCode.STOPPED:
        return PytestRunnerState.STOPPED
    if exit_code == PyTestFlyExitCode.NONE:
        return PytestRunnerState.QUEUED if info.pid is None else PytestRunnerState.RUNNING
    log.error(f"unknown exit code {exit_code} for test {info.name}, defaulting to QUEUED")
    return PytestRunnerState.QUEUED


def latest_info_per_name(infos: list[PytestProcessInfo]) -> dict[str, PytestProcessInfo]:
    """Return the most recent :class:`PytestProcessInfo` per test name (by ``time_stamp``)."""
    latest: dict[str, PytestProcessInfo] = {}
    for info in infos:
        prior = latest.get(info.name)
        if prior is None or info.time_stamp >= prior.time_stamp:
            latest[info.name] = info
    return latest


def latest_states(infos: list[PytestProcessInfo]) -> dict[str, PytestRunnerState]:
    """Return each test's current state, derived from its most recent record."""
    return {name: state_of(info) for name, info in latest_info_per_name(infos).items()}


class PytestRunState:
    """Display-facing state of one test, derived from its (time-ordered) record list.

    The record list must be ordered oldest-to-newest: the *last* element is taken as the
    test's current record. (Callers that hold an unordered pile of records should reduce
    it with :func:`latest_info_per_name` / :func:`latest_states` instead, which select by
    ``time_stamp``.)
    """

    @typechecked()
    def __init__(self, run_infos: list[PytestProcessInfo]):
        if len(run_infos) > 0:
            last_run_info = run_infos[-1]
            self._name = last_run_info.name
            self._state = state_of(last_run_info)
        else:
            self._name = None
            self._state = PytestRunnerState.QUEUED

    def get_state(self) -> PytestRunnerState:
        """Return the classified :class:`PytestRunnerState`."""
        return self._state

    def get_string(self) -> str:
        """Return the state's display string (e.g. ``"Running"``)."""
        return self._state.value

    def get_name(self) -> str | None:
        """Return the test name from the latest record, or ``None`` if there were no records."""
        return self._name
