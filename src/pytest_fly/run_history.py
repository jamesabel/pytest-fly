"""
Run-history summarization — reduces multi-run DB records into per-run summaries.

Groups :class:`PytestProcessInfo` records by ``run_guid`` and derives one
:class:`RunHistorySummary` per run (start time, duration, pass/fail statistics, and the
list of failed tests) for the History tab.  Kept free of Qt so it can be tested headless,
matching :mod:`pytest_fly.pytest_runner.run_state` which it builds on.
"""

from dataclasses import dataclass

from .interfaces import PytestProcessInfo, PytestRunnerState
from .pytest_runner.run_state import TERMINAL_STATES, latest_info_per_name, state_of


@dataclass(frozen=True)
class RunHistorySummary:
    """Aggregate view of one test run, derived from its DB records."""

    run_guid: str
    put_version: str  # program-under-test label of the run, or "" if none was recorded
    start_ts: float  # earliest record timestamp (wall-clock start of the run)
    end_ts: float  # latest record timestamp (end of the run, or "so far" for an in-progress run)
    n_pass: int
    n_fail: int
    n_other: int  # everything else: terminated, stopped, and still queued/running tests
    is_complete: bool  # True when every test in the run reached a terminal state
    failed_tests: tuple[str, ...]  # node_ids whose latest state is FAIL, sorted

    @property
    def duration(self) -> float:
        """Run wall-clock duration in seconds (elapsed-so-far for an in-progress run)."""
        return self.end_ts - self.start_ts

    @property
    def n_total(self) -> int:
        """Total number of tests in the run."""
        return self.n_pass + self.n_fail + self.n_other


def build_run_history(infos: list[PytestProcessInfo]) -> list[RunHistorySummary]:
    """Group *infos* by run and summarize each run, most recent first.

    Ordering relies on run GUIDs being UUIDv7 (time-ordered; see
    :func:`pytest_fly.guid.generate_uuid`), the same rule the DB layer uses to select
    the most recent run.
    """
    infos_by_run: dict[str, list[PytestProcessInfo]] = {}
    for info in infos:
        infos_by_run.setdefault(info.run_guid, []).append(info)

    summaries = []
    for run_guid in sorted(infos_by_run, reverse=True):
        run_infos = infos_by_run[run_guid]
        states = {name: state_of(info) for name, info in latest_info_per_name(run_infos).items()}
        n_pass = sum(1 for state in states.values() if state == PytestRunnerState.PASS)
        n_fail = sum(1 for state in states.values() if state == PytestRunnerState.FAIL)
        # The version label is only stamped on some records (status records carry ""); take it
        # from the newest record that has one.
        put_version = next((info.put_version for info in sorted(run_infos, key=lambda i: i.time_stamp, reverse=True) if info.put_version), "")
        summaries.append(
            RunHistorySummary(
                run_guid=run_guid,
                put_version=put_version,
                start_ts=min(info.time_stamp for info in run_infos),
                end_ts=max(info.time_stamp for info in run_infos),
                n_pass=n_pass,
                n_fail=n_fail,
                n_other=len(states) - n_pass - n_fail,
                is_complete=all(state in TERMINAL_STATES for state in states.values()),
                failed_tests=tuple(sorted(name for name, state in states.items() if state == PytestRunnerState.FAIL)),
            )
        )
    return summaries
