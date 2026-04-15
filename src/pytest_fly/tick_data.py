"""
Pre-computed data shared across all GUI tabs on each refresh tick.

Computing grouping, time windows, and run states once per tick (instead of
redundantly in each tab) eliminates the majority of per-tick overhead.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .interfaces import PytestProcessInfo


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
    last_pass_data: dict[str, tuple[float, float]] = field(default_factory=dict)  # test_name -> (start_timestamp, duration_seconds) from most recent passing run
