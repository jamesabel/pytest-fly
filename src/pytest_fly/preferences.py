"""
Persistent user preferences backed by a per-PUT SQLite file via the *pref* library.

Each program under test (PUT) gets its own preferences DB at
``<PUT>/.pytest-fly/preferences.db``.  The PUT path is established at
application startup via :func:`init_preferences_for_put`; every preference
accessor downstream — including :class:`FlyPreferences` and the ordering-aspect
:class:`PrefOrderedSet` — resolves storage relative to that path.
"""

from enum import IntEnum
from pathlib import Path

from attr import attrib, attrs
from pref import Pref, PrefOrderedSet

from .__version__ import application_name, author
from .interfaces import OrderingAspect, RunMode
from .platform import get_performance_core_count

preferences_file_name = "preferences.db"
preferences_dir_name = f".{application_name}"  # ".pytest-fly" — hidden dir inside the PUT root
_ordering_aspects_table = "ordering_aspects"
_default_ordering_aspect_seed: list[OrderingAspect] = [OrderingAspect.FAILED_FIRST, OrderingAspect.NEVER_RUN_FIRST]

scheduler_time_quantum_default = 1.0
refresh_rate_default = 3.0
utilization_high_threshold_default = 0.8
utilization_low_threshold_default = 0.5
commit_warning_threshold_default = 0.85  # warn when system commit charge exceeds this fraction of the commit limit
run_with_coverage_default = True
tooltip_line_limit_default = 40  # max lines shown in pytest-output tooltips before truncation
chart_window_minutes_default = 5.0  # width of the system-metrics chart time window on the Run tab, in minutes
graph_font_size_default = 10  # point size of the font used in the Progress Graph tab


class ParallelismControl(IntEnum):
    """How test parallelism is determined."""

    SERIAL = 0  # run tests serially (processes=1)
    PARALLEL = 1  # run "processes" number of tests in parallel
    DYNAMIC = 2  # automatically dynamically determine max number of processes to run in parallel, while trying to avoid high utilization thresholds (see utilization_high_threshold)


_active_put_path: Path | None = None


def init_preferences_for_put(put_path: Path) -> None:
    """Bind preference storage to ``put_path`` for the current process.

    Must be called once at startup before any :func:`get_pref` or
    :func:`get_ordering_aspects_set` call — the PUT path drives the SQLite
    location for both :class:`FlyPreferences` and the ordering-aspect
    :class:`PrefOrderedSet`.  Calling again with a different path invalidates
    the cached pref instance so the next access reopens against the new PUT.
    """
    global _active_put_path
    resolved = put_path.resolve()
    if _active_put_path != resolved:
        _active_put_path = resolved
        reset_pref_cache()


def get_active_put_path() -> Path:
    """Return the PUT path bound via :func:`init_preferences_for_put`."""
    if _active_put_path is None:
        raise RuntimeError("init_preferences_for_put() must be called before accessing preferences")
    return _active_put_path


def get_preferences_db_path() -> Path:
    """Return the path to the per-PUT preferences DB."""
    return Path(get_active_put_path(), preferences_dir_name, preferences_file_name)


def _ensure_preferences_dir() -> None:
    get_preferences_db_path().parent.mkdir(parents=True, exist_ok=True)


@attrs
class FlyPreferences(Pref):
    """Persistent per-PUT user preferences backed by a local SQLite file."""

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

    commit_warning_threshold: float = attrib(default=commit_warning_threshold_default)  # warn when system commit charge exceeds this fraction of the commit limit

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

    test_results_db_dir: str = attrib(default="")  # override directory for the test-results SQLite DB; empty means use the platform default

    perf_logging: bool = attrib(default=False)  # log per-tick phase timings (db query, build_tick_data, each tab update) to diagnose UI lag

    def get_sqlite_path(self) -> Path:
        # Override pref's default appdirs-based resolution so storage lives under the active PUT.
        path = get_preferences_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


class FlyOrderedSet(PrefOrderedSet):
    """:class:`PrefOrderedSet` with per-PUT SQLite storage."""

    def get_sqlite_path(self) -> Path:
        path = get_preferences_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


_cached_pref: FlyPreferences | None = None
_cached_pref_path: Path | None = None


def get_pref() -> FlyPreferences:
    """Return a :class:`FlyPreferences` instance (reads from / auto-saves to disk).

    The instance is cached process-wide and keyed on the resolved per-PUT
    storage path, so switching PUT via :func:`init_preferences_for_put` will
    transparently reopen the right DB on the next access.  Constructing
    ``FlyPreferences`` issues one SELECT per attribute, so caching matters for
    UI tick performance.
    """
    global _cached_pref, _cached_pref_path
    current_path = get_preferences_db_path()
    if _cached_pref is None or _cached_pref_path != current_path:
        _cached_pref = FlyPreferences(application_name, author, file_name=preferences_file_name)
        _cached_pref_path = current_path
    return _cached_pref


def reset_pref_cache() -> None:
    """Drop the cached :class:`FlyPreferences` instance.  Intended for tests."""
    global _cached_pref, _cached_pref_path
    _cached_pref = None
    _cached_pref_path = None


def get_ordering_aspects_set() -> FlyOrderedSet:
    """Return the :class:`FlyOrderedSet` backing the enabled-and-ordered aspect list."""
    return FlyOrderedSet(application_name, author, table=_ordering_aspects_table, file_name=preferences_file_name)


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
