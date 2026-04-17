"""
Pre-computed data shared across all GUI tabs on each refresh tick.

Computing grouping, time windows, and run states once per tick (instead of
redundantly in each tab) eliminates the majority of per-tick overhead.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .interfaces import PutVersionInfo, PytestProcessInfo


@dataclass
class TickData:
    """Bundle of pre-computed values produced once per refresh tick and consumed by all tabs."""

    process_infos: list[PytestProcessInfo]
    infos_by_name: dict[str, list[PytestProcessInfo]] = field(default_factory=dict)
    # PytestRunState keyed by test name — typed as Any to avoid circular import with pytest_runner
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

    @property
    def effective_min_time_stamp(self) -> float | None:
        """Graph time-axis origin: prefer the explicit run-start timestamp so copied
        prior-run records (RESUME mode) don't stretch the axis; otherwise fall back
        to the earliest observed record timestamp."""
        return self.current_run_start if self.current_run_start is not None else self.min_time_stamp
