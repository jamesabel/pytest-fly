"""
Persistent user preferences backed by a local SQLite file via the *pref* library.

Default values for parallelism, refresh rate, and utilization thresholds are
defined here so both the preference class and the configuration tab can share
them without circular imports.
"""

from enum import IntEnum

from attr import attrib, attrs
from pref import Pref

from .__version__ import application_name, author
from .interfaces import RunMode, TestOrder
from .platform import get_performance_core_count

preferences_file_name = f"{application_name}_preferences.db"

scheduler_time_quantum_default = 1.0
refresh_rate_default = 3.0
utilization_high_threshold_default = 0.8
utilization_low_threshold_default = 0.5
run_with_coverage_default = True
tooltip_line_limit_default = 40  # max lines shown in pytest-output tooltips before truncation
chart_window_minutes_default = 5.0  # width of the system-metrics chart time window on the Run tab, in minutes


class ParallelismControl(IntEnum):
    """How test parallelism is determined."""

    SERIAL = 0  # run tests serially (processes=1)
    PARALLEL = 1  # run "processes" number of tests in parallel
    DYNAMIC = 2  # automatically dynamically determine max number of processes to run in parallel, while trying to avoid high utilization thresholds (see utilization_high_threshold)


@attrs
class FlyPreferences(Pref):
    """Persistent user preferences backed by a local SQLite file via the *pref* library."""

    window_x: int = attrib(default=-1)
    window_y: int = attrib(default=-1)
    window_width: int = attrib(default=-1)
    window_height: int = attrib(default=-1)

    verbose: bool = attrib(default=False)
    refresh_rate: float = attrib(default=refresh_rate_default)  # display minimum refresh rate in seconds

    parallelism: ParallelismControl = attrib(default=ParallelismControl.SERIAL)  # 0=serial, 1=parallel, 2=dynamic
    processes: int = attrib(default=get_performance_core_count())  # fixed number of processes to use for "PARALLEL" mode

    utilization_high_threshold: float = attrib(default=utilization_high_threshold_default)  # above this threshold is considered high utilization
    utilization_low_threshold: float = attrib(default=utilization_low_threshold_default)  # below this threshold is considered low utilization

    run_mode: RunMode = attrib(default=RunMode.CHECK)  # 0=restart all tests, 1=resume, 2=resume if possible (i.e., the program version under test has not changed)

    test_order: TestOrder = attrib(default=TestOrder.PYTEST)  # 0=pytest default order, 1=coverage efficiency order

    tooltip_line_limit: int = attrib(default=tooltip_line_limit_default)  # max lines of pytest output shown in a tooltip before truncation

    chart_window_minutes: float = attrib(default=chart_window_minutes_default)  # Run-tab system-metrics chart window (minutes)

    run_tab_splitter_state: str = attrib(default="")  # Run-tab top-vs-failed-tests splitter (QSplitter.saveState() hex-encoded)

    target_project_path: str = attrib(default="")  # absolute path to the program under test; empty means auto-detect from cwd at run time

    perf_logging: bool = attrib(default=False)  # log per-tick phase timings (db query, build_tick_data, each tab update) to diagnose UI lag


def get_pref() -> FlyPreferences:
    """Return a :class:`FlyPreferences` instance (reads from / auto-saves to disk)."""
    return FlyPreferences(application_name, author, file_name=preferences_file_name)
