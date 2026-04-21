"""
Persistent user preferences backed by a local SQLite file via the *pref* library.

Default values for parallelism, refresh rate, and utilization thresholds are
defined here so both the preference class and the configuration tab can share
them without circular imports.
"""

import json
from enum import IntEnum

from attr import attrib, attrs
from pref import Pref

from .__version__ import application_name, author
from .interfaces import OrderingAspect, RunMode
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

    run_mode: RunMode = attrib(default=RunMode.CHECK)  # RESTART=0, RESUME=1, CHECK=2 (Resume with PUT-change check — see resume_skip_put_check)

    resume_skip_put_check: bool = attrib(default=False)  # when True, Resume forces a resume even if the PUT has changed; when False, a PUT change triggers a Restart

    # JSON-encoded list of [{"aspect": <OrderingAspect.value>, "enabled": bool}, ...]
    # in priority order (index 0 = highest priority).  Empty means "use default seed";
    # see :func:`get_ordering_aspects`.
    ordering_aspects: str = attrib(default="")

    tooltip_line_limit: int = attrib(default=tooltip_line_limit_default)  # max lines of pytest output shown in a tooltip before truncation

    chart_window_minutes: float = attrib(default=chart_window_minutes_default)  # Run-tab system-metrics chart window (minutes)

    run_tab_splitter_state: str = attrib(default="")  # Run-tab top-vs-failed-tests splitter (QSplitter.saveState() hex-encoded)

    target_project_path: str = attrib(default="")  # absolute path to the program under test; empty means auto-detect from cwd at run time

    perf_logging: bool = attrib(default=False)  # log per-tick phase timings (db query, build_tick_data, each tab update) to diagnose UI lag


def get_pref() -> FlyPreferences:
    """Return a :class:`FlyPreferences` instance (reads from / auto-saves to disk)."""
    return FlyPreferences(application_name, author, file_name=preferences_file_name)


# Default ordering-aspect list when the user has no stored preference.  Failed-first
# and never-run-first are enabled by default to preserve a sensible out-of-the-box
# feedback loop; the others are present but disabled so users can discover them.
_default_ordering_aspects: list[tuple[OrderingAspect, bool]] = [
    (OrderingAspect.FAILED_FIRST, True),
    (OrderingAspect.NEVER_RUN_FIRST, True),
    (OrderingAspect.LONGEST_PRIOR_FIRST, False),
    (OrderingAspect.COVERAGE_EFFICIENCY, False),
]


def get_ordering_aspects(pref: FlyPreferences) -> list[tuple[OrderingAspect, bool]]:
    """Parse :attr:`FlyPreferences.ordering_aspects` into an ordered list.

    Guarantees that every :class:`OrderingAspect` appears exactly once.  Unknown
    aspect values in the stored JSON are discarded; aspects missing from the
    stored JSON are appended in :class:`OrderingAspect` declaration order, with
    the default enable state from :data:`_default_ordering_aspects`.

    :param pref: Preferences instance.
    :return: List of ``(aspect, enabled)`` tuples in priority order.
    """
    try:
        raw = json.loads(pref.ordering_aspects) if pref.ordering_aspects else []
    except (ValueError, TypeError):
        raw = []

    seen: set[OrderingAspect] = set()
    result: list[tuple[OrderingAspect, bool]] = []
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            try:
                aspect = OrderingAspect(entry.get("aspect"))
            except ValueError:
                continue
            if aspect in seen:
                continue
            seen.add(aspect)
            result.append((aspect, bool(entry.get("enabled", False))))

    default_enabled = {aspect: enabled for aspect, enabled in _default_ordering_aspects}
    for aspect, enabled in _default_ordering_aspects:
        if aspect not in seen:
            # Missing aspect — append with its default enable state.
            result.append((aspect, default_enabled[aspect]))

    return result


def set_ordering_aspects(pref: FlyPreferences, aspects: list[tuple[OrderingAspect, bool]]) -> None:
    """Serialise *aspects* into :attr:`FlyPreferences.ordering_aspects`."""
    pref.ordering_aspects = json.dumps([{"aspect": a.value, "enabled": bool(enabled)} for a, enabled in aspects])
