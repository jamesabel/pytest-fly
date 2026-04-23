"""
Persistent user preferences backed by a local SQLite file via the *pref* library.

Default values for parallelism, refresh rate, and utilization thresholds are
defined here so both the preference class and the configuration tab can share
them without circular imports.
"""

from enum import IntEnum
from pathlib import Path

from attr import attrib, attrs
from pref import Pref, PrefOrderedSet
from pref.pref import appdirs as _pref_appdirs

from .__version__ import application_name, author
from .interfaces import OrderingAspect, RunMode
from .platform import get_performance_core_count

preferences_file_name = f"{application_name}_preferences.db"
_ordering_aspects_table = "ordering_aspects"
_default_ordering_aspect_seed: list[OrderingAspect] = [OrderingAspect.FAILED_FIRST, OrderingAspect.NEVER_RUN_FIRST]

scheduler_time_quantum_default = 1.0
refresh_rate_default = 3.0
utilization_high_threshold_default = 0.8
utilization_low_threshold_default = 0.5
run_with_coverage_default = True
tooltip_line_limit_default = 40  # max lines shown in pytest-output tooltips before truncation
chart_window_minutes_default = 5.0  # width of the system-metrics chart time window on the Run tab, in minutes
graph_font_size_default = 10  # point size of the font used in the Progress Graph tab


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

    # True once the ordering-aspect PrefOrderedSet has been seeded with defaults.
    # Guards against re-seeding a set the user has intentionally emptied.
    ordering_aspects_seeded: bool = attrib(default=False)

    tooltip_line_limit: int = attrib(default=tooltip_line_limit_default)  # max lines of pytest output shown in a tooltip before truncation

    chart_window_minutes: float = attrib(default=chart_window_minutes_default)  # Run-tab system-metrics chart window (minutes)

    graph_font_size: int = attrib(default=graph_font_size_default)  # Progress Graph tab font size, in points

    run_tab_splitter_state: str = attrib(default="")  # Run-tab top-vs-failed-tests splitter (QSplitter.saveState() hex-encoded)
    run_tab_bottom_splitter_state: str = attrib(default="")  # Run-tab bottom pane: failed-tests-vs-live-output splitter (QSplitter.saveState() hex-encoded)

    target_project_path: str = attrib(default="")  # absolute path to the program under test; empty means auto-detect from cwd at run time

    perf_logging: bool = attrib(default=False)  # log per-tick phase timings (db query, build_tick_data, each tab update) to diagnose UI lag


_cached_pref: FlyPreferences | None = None
_cached_pref_path: Path | None = None


def _resolve_pref_path() -> Path:
    """Resolve the SQLite path that ``FlyPreferences`` would open right now.

    Mirrors ``Pref.get_sqlite_path`` and uses pref's own ``appdirs`` import so
    test fixtures that monkeypatch ``pref.pref.appdirs.user_config_dir`` are
    honored — this is what lets the cache invalidate across tests with isolated
    storage dirs.
    """
    return Path(_pref_appdirs.user_config_dir(application_name, author), preferences_file_name)


def get_pref() -> FlyPreferences:
    """Return a :class:`FlyPreferences` instance (reads from / auto-saves to disk).

    The instance is cached process-wide.  Constructing ``FlyPreferences``
    reopens the backing ``SqliteDict`` and issues one SELECT per attribute,
    so calling ``get_pref()`` on every tick — including from each progress
    bar — was a measurable contributor to UI latency.  Writes go through
    ``FlyPreferences.__setattr__`` directly to disk, so the cached instance
    stays consistent with persistent storage.

    The cache is keyed on the resolved storage path, so tests that redirect
    pref storage to a tmp dir transparently get a fresh instance.
    """
    global _cached_pref, _cached_pref_path
    current_path = _resolve_pref_path()
    if _cached_pref is None or _cached_pref_path != current_path:
        _cached_pref = FlyPreferences(application_name, author, file_name=preferences_file_name)
        _cached_pref_path = current_path
    return _cached_pref


def get_ordering_aspects_set() -> PrefOrderedSet:
    """Return the :class:`PrefOrderedSet` backing the enabled-and-ordered aspect list."""
    return PrefOrderedSet(application_name, author, table=_ordering_aspects_table, file_name=preferences_file_name)


def get_ordering_aspects_ordered() -> list[OrderingAspect]:
    """Return enabled aspects in priority order; seed defaults on first ever call."""
    pref = get_pref()
    aspect_set = get_ordering_aspects_set()
    if not pref.ordering_aspects_seeded:
        aspect_set.set([a.value for a in _default_ordering_aspect_seed])
        pref.ordering_aspects_seeded = True
    result: list[OrderingAspect] = []
    for value in aspect_set.get():
        try:
            result.append(OrderingAspect(value))
        except ValueError:
            continue  # ignore stale / renamed aspect values
    return result


def set_ordering_aspects_ordered(aspects: list[OrderingAspect]) -> None:
    """Persist the enabled-and-ordered aspect list."""
    get_pref().ordering_aspects_seeded = True  # any explicit write counts as seeded
    get_ordering_aspects_set().set([a.value for a in aspects])
