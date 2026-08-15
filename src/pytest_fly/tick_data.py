"""
Pre-computed data shared across all GUI tabs on each refresh tick.

Computing grouping, time windows, and run states once per tick (instead of
redundantly in each tab) eliminates the majority of per-tick overhead.  This module
holds both the :class:`TickData` container and the pure (Qt-free) record-transformation
helpers that build it, so widget tests can construct tick data without importing any
window class.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field, replace

from .interfaces import PutVersionInfo, PytestProcessInfo, PytestRunnerState
from .pytest_runner.run_state import PytestRunState


@dataclass
class TickData:
    """Bundle of pre-computed values produced once per refresh tick and consumed by all tabs."""

    process_infos: list[PytestProcessInfo]
    infos_by_name: dict[str, list[PytestProcessInfo]] = field(default_factory=dict)
    # PytestRunState keyed by test name
    run_states: dict = field(default_factory=dict)
    min_time_stamp: float | None = None
    max_time_stamp: float | None = None
    # Time window considering only records where pid is set (process has started)
    min_time_stamp_started: float | None = None
    max_time_stamp_started: float | None = None
    prior_durations: dict[str, float] = field(default_factory=dict)
    num_processes: int = 1
    coverage_history: list[tuple[float, float]] = field(default_factory=list)  # (timestamp, coverage_pct 0.0-1.0)
    per_test_coverage: dict[str, float] = field(default_factory=dict)  # test_name -> coverage_pct 0.0-1.0
    covered_lines: int = 0  # lines executed by all completed tests combined
    total_lines: int = 0  # total executable lines in the source
    average_parallelism: float | None = None  # average number of simultaneously running test processes
    current_run_start: float | None = None  # wall-clock timestamp captured when Run was pressed; used as the graph time-axis origin
    last_pass_data: dict[str, tuple[float, float]] = field(default_factory=dict)  # test_name -> (start_timestamp, duration_seconds) from most recent passing run
    soft_stop_requested: bool = False
    singleton_names: set[str] = field(default_factory=set)  # node_ids of tests marked with @pytest.mark.singleton — displayed last in test-listing tabs
    put_version_info: PutVersionInfo | None = None  # program-under-test metadata detected at the start of the current run
    # Stall watchdog snapshot (typed loosely as `object` to avoid a hard dependency on pytest_runner). None when no watchdog is running.
    stall_info: object | None = None
    # Resource guard snapshot (typed loosely as `object`, as above). None when the guard is not enabled/running.
    resource_guard_info: object | None = None
    run_complete_stuck: list[str] = field(default_factory=list)  # non-terminal tests when the run is otherwise finished (Part D); drives the "finished — N stuck" message

    @property
    def effective_min_time_stamp(self) -> float | None:
        """Graph time-axis origin: prefer the explicit run-start timestamp so copied
        prior-run records (RESUME mode) don't stretch the axis; otherwise fall back
        to the earliest observed record timestamp."""
        return self.current_run_start if self.current_run_start is not None else self.min_time_stamp


def group_process_infos_by_name(process_infos: list[PytestProcessInfo]) -> dict[str, list[PytestProcessInfo]]:
    """
    Group a flat list of process info records by test name.

    :param process_infos: Flat list of ``PytestProcessInfo`` objects.
    :return: Dictionary mapping each test name to its list of info records, in encounter order.
    """
    grouped: dict[str, list[PytestProcessInfo]] = defaultdict(list)
    for info in process_infos:
        grouped[info.name].append(info)
    return grouped


def compute_time_window(process_infos: list[PytestProcessInfo], require_pid: bool = False) -> tuple[float | None, float | None]:
    """
    Compute the minimum and maximum timestamps from a list of process info records.

    :param process_infos: List of ``PytestProcessInfo`` objects.
    :param require_pid: If ``True``, only consider records where ``pid`` is not ``None``
                        (i.e. the process has actually started).
    :return: ``(min_timestamp, max_timestamp)`` tuple, or ``(None, None)`` if no records qualify.
    """
    min_ts: float | None = None
    max_ts: float | None = None
    for info in process_infos:
        if require_pid and info.pid is None:
            continue
        if min_ts is None or info.time_stamp < min_ts:
            min_ts = info.time_stamp
        if max_ts is None or info.time_stamp > max_ts:
            max_ts = info.time_stamp
    return min_ts, max_ts


def count_test_states(run_states: dict) -> dict:
    """Count tests by their current PytestRunnerState."""
    counts = defaultdict(int)
    for run_state in run_states.values():
        counts[run_state.get_state()] += 1
    return counts


def first_start_timestamp(infos: list[PytestProcessInfo]) -> float | None:
    """Return the timestamp of a test's first record with a pid (when it actually started), or ``None``."""
    return next((info.time_stamp for info in infos if info.pid is not None), None)


def extract_test_duration(infos: list) -> tuple[float | None, float | None]:
    """
    Extract start and end timestamps from a test's process info records.

    :param infos: List of PytestProcessInfo for a single test.
    :return: (start_timestamp, end_timestamp) or (None, None).
    """
    from .interfaces import PyTestFlyExitCode

    start = first_start_timestamp(infos)
    end = None
    for info in infos:
        if info.exit_code != PyTestFlyExitCode.NONE:
            end = info.time_stamp
    return start, end


def compute_average_parallelism(infos_by_name: dict[str, list[PytestProcessInfo]]) -> float | None:
    """
    Compute the average number of simultaneously running test processes.

    Average parallelism = total_test_time / wall_clock_time.

    For in-progress tests (started but not finished), the current time is used
    as the end time so the metric updates live during a run.

    :param infos_by_name: Process info records grouped by test name.
    :return: Average parallelism, or ``None`` if insufficient data.
    """
    total_test_time = 0.0
    all_starts: list[float] = []
    all_ends: list[float] = []
    now = time.time()

    for infos in infos_by_name.values():
        start, end = extract_test_duration(infos)
        if start is not None:
            if end is None:
                end = now  # test still running
            total_test_time += end - start
            all_starts.append(start)
            all_ends.append(end)

    if not all_starts:
        return None

    wall_clock = max(all_ends) - min(all_starts)
    if wall_clock <= 0:
        return None

    return total_test_time / wall_clock


def build_tick_data(
    process_infos: list,
    prior_durations: dict[str, float] | None = None,
    num_processes: int = 1,
    current_run_start: float | None = None,
    singleton_names: set[str] | None = None,
    put_version_info: PutVersionInfo | None = None,
) -> TickData:
    """
    Build a :class:`TickData` bundle from a flat list of process info records.

    Performs grouping, time-window computation, and run-state construction
    once so that all tabs can share the pre-computed results.

    ``infos_by_name`` and ``run_states`` are ordered alphabetically by test name
    with singleton tests last, so all tabs that iterate these dicts render in
    the same order (matching the runner's execution order).

    :param process_infos: Flat list of :class:`PytestProcessInfo` objects from the DB.
    :param prior_durations: Optional mapping of test name to prior run duration (seconds), used for ETA.
    :param num_processes: Number of parallel worker processes (used for ETA wall-clock estimation).
    :param current_run_start: Wall-clock timestamp captured when the Run button was pressed, used
        as the graph time-axis origin.  Passed in explicitly because RESUME mode copies prior-run
        records (including their original QUEUED records with ``exit_code == NONE``), so the origin
        cannot be derived reliably from DB records alone.
    :param singleton_names: Node ids of tests marked ``@pytest.mark.singleton``; these are sorted
        last in the output dicts to match the runner's end-of-queue placement.
    :param put_version_info: Program-under-test metadata detected at the start of the run,
        surfaced to the tabs via :attr:`TickData.put_version_info`.
    :return: A fully populated :class:`TickData` instance.
    """
    singletons = singleton_names if singleton_names is not None else set()

    # RESUME mode copies prior-run records for already-passed tests into the current run so
    # they appear in every GUI tab.  Those copies keep their genuine historical timestamps in
    # the DB (so query_last_pass / the "Last Pass Start" column report real wall-clock times),
    # but the Progress Graph and Run-tab status use current_run_start as their time-axis origin,
    # so historical records would fall off the left edge.  Shift the carried-over records (those
    # predating the run's start) onto the current run's timeline here, at render time, preserving
    # their relative spacing and leaving the DB untouched.  Durations are delta-invariant, so the
    # table's Runtime column is unaffected.
    if current_run_start is not None:
        earliest_carried = min((info.time_stamp for info in process_infos if info.time_stamp < current_run_start), default=None)
        if earliest_carried is not None:
            delta = current_run_start - earliest_carried
            process_infos = [replace(info, time_stamp=info.time_stamp + delta) if info.time_stamp < current_run_start else info for info in process_infos]

    grouped = group_process_infos_by_name(process_infos)
    ordered_names = sorted(grouped, key=lambda n: (n in singletons, n))
    infos_by_name = {name: grouped[name] for name in ordered_names}
    run_states = {name: PytestRunState(infos_by_name[name]) for name in ordered_names}
    min_ts, max_ts = compute_time_window(process_infos)
    min_ts_s, max_ts_s = compute_time_window(process_infos, require_pid=True)

    # While any test is running, anchor the time-axis right edge to wall-clock now.
    # Otherwise max_ts is frozen at the latest STARTED record's timestamp, so running-test
    # bars (whose right edge is time.time()) overflow far past the chart and get clipped.
    if max_ts is not None and any(rs.get_state() == PytestRunnerState.RUNNING for rs in run_states.values()):
        max_ts = max(max_ts, time.time())

    return TickData(
        process_infos=process_infos,
        infos_by_name=infos_by_name,
        run_states=run_states,
        min_time_stamp=min_ts,
        max_time_stamp=max_ts,
        min_time_stamp_started=min_ts_s,
        max_time_stamp_started=max_ts_s,
        prior_durations=prior_durations if prior_durations is not None else {},
        num_processes=num_processes,
        average_parallelism=compute_average_parallelism(infos_by_name),
        current_run_start=current_run_start,
        singleton_names=singletons,
        put_version_info=put_version_info,
    )
