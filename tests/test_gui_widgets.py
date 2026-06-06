"""Additional widget tests targeting paint paths and integration points."""

import dataclasses
import time

from PySide6.QtCore import QRect, QSize

from pytest_fly.gui.coverage_tab import CoverageTab
from pytest_fly.gui.gui_main import FlyAppMainWindow, build_tick_data
from pytest_fly.gui.run_tab.control_window import ControlWindow
from pytest_fly.gui.run_tab.system_metrics_window import SystemMetricsWindow
from pytest_fly.interfaces import (
    PyTestFlyExitCode,
    PytestProcessInfo,
    RunMode,
    ScheduledTest,
)
from pytest_fly.preferences import get_pref
from pytest_fly.pytest_runner.system_monitor import SystemMonitorSample

from .paths import get_temp_dir


def _make_samples(n: int, now: float | None = None) -> list[SystemMonitorSample]:
    if now is None:
        now = time.time()
    samples = []
    for i in range(n):
        samples.append(
            SystemMonitorSample(
                time_stamp=now - (n - i) * 0.5,
                cpu_percent=10.0 + i,
                memory_percent=40.0 + i,
                memory_used_gb=4.0 + i * 0.1,
                memory_total_gb=16.0,
                disk_read_mbps=5.0 + i,
                disk_write_mbps=2.0 + i,
                net_sent_mbps=1.0 + i * 0.1,
                net_recv_mbps=3.0 + i * 0.1,
            )
        )
    return samples


def _force_paint(widget, width: int = 600, height: int = 400) -> None:
    """Force the widget to produce a paintEvent by rendering it to a pixmap."""
    widget.resize(QSize(width, height))
    widget.grab()


def test_system_metrics_window_ingest_and_paint(qtbot):
    """SystemMetricsWindow should accept samples and paint all four sub-charts."""
    window = SystemMetricsWindow(None)
    qtbot.addWidget(window)

    window.ingest_samples(_make_samples(5))
    window.update_tick()

    _force_paint(window, 800, 600)
    _force_paint(window._cpu_chart, 300, 150)
    _force_paint(window._memory_chart, 300, 150)
    _force_paint(window._disk_chart, 300, 150)
    _force_paint(window._network_chart, 300, 150)


def test_system_metrics_window_prunes_stale_samples(qtbot):
    """update_tick() should drop samples outside the configured time window."""
    window = SystemMetricsWindow(None)
    qtbot.addWidget(window)

    # Stale sample from an hour ago — should be pruned when update_tick runs.
    stale = SystemMonitorSample(
        time_stamp=time.time() - 3600.0,
        cpu_percent=50.0,
        memory_percent=50.0,
        memory_used_gb=8.0,
        memory_total_gb=16.0,
        disk_read_mbps=0.0,
        disk_write_mbps=0.0,
        net_sent_mbps=0.0,
        net_recv_mbps=0.0,
    )
    fresh = _make_samples(2)

    window.ingest_samples([stale, *fresh])
    window.update_tick()

    assert all(s.time_stamp > time.time() - 3600 for s in window._samples)


def test_system_metrics_window_empty_paint(qtbot):
    """SystemMetricsWindow should paint cleanly when no samples have been ingested."""
    window = SystemMetricsWindow(None)
    qtbot.addWidget(window)
    window.update_tick()
    _force_paint(window, 800, 600)


def test_system_metrics_window_activity_chart(qtbot):
    """The Activity chart should record a per-tick running/idle/stalled sample and paint it."""
    from pytest_fly.pytest_runner.pytest_runner import PytestRunState, StallInfo
    from pytest_fly.tick_data import TickData

    window = SystemMetricsWindow(None)
    qtbot.addWidget(window)

    now = time.time()
    run_states = {
        "tests/test_a.py": PytestRunState([PytestProcessInfo("g", "tests/test_a.py", 111, PyTestFlyExitCode.NONE, None, time_stamp=now)]),
        "tests/test_b.py": PytestRunState([PytestProcessInfo("g", "tests/test_b.py", 222, PyTestFlyExitCode.NONE, None, time_stamp=now)]),
    }
    tick = TickData(process_infos=[], run_states=run_states)
    tick.stall_info = StallInfo(stalled=True, idle_pids=[111, 222], seconds_since_progress=700.0)

    window.update_tick(tick)

    assert len(window._activity_samples) == 1
    sample = window._activity_samples[-1]
    assert sample.running == 2
    assert sample.idle == 2
    assert sample.stalled is True

    _force_paint(window, 800, 600)
    _force_paint(window._activity_chart, 300, 150)


def test_activity_chart_y_labels_are_distinct_integers(qtbot):
    """Integer-count charts must never render duplicate y-axis labels (regression).

    With fixed 0.25/0.5/0.75/1.0 fractions, a small ``y_max`` (e.g. 1) rounded to integers
    produced duplicates like 0, 0, 1, 1. Whole-number ticks keep every label distinct and
    put the top tick exactly on ``y_max``.
    """
    chart = SystemMetricsWindow(None)._activity_chart
    for y_max in [1, 2, 3, 4, 5, 7, 8, 10, 16, 19, 32]:
        ticks = chart._y_grid_ticks(float(y_max))
        labels = [chart._format_y_label(value) for value in ticks]
        assert len(labels) == len(set(labels)), f"duplicate y labels for {y_max=}: {labels}"
        assert all("." not in label for label in labels), f"non-integer y label for {y_max=}: {labels}"
        assert ticks[-1] == float(y_max), f"top tick should equal y_max for {y_max=}: {ticks}"


def test_commit_warning_latches_until_cleared(qtbot):
    """The commit-charge warning persists after the charge drops back, until the user clears it."""
    window = SystemMetricsWindow(None)
    qtbot.addWidget(window)

    def _commit_sample(time_stamp: float, commit_percent: float) -> SystemMonitorSample:
        base = _make_samples(1, now=time_stamp + 0.5)[0]
        return dataclasses.replace(base, time_stamp=time_stamp, commit_total_gb=32.0, commit_percent=commit_percent)

    threshold = get_pref().commit_warning_threshold
    now = time.time()
    over = _commit_sample(now, (threshold + 0.05) * 100.0)
    under = _commit_sample(now + 0.5, 10.0)

    # Cross the threshold → warning raised.
    window.ingest_samples([over])
    window.update_tick()
    assert window._commit_warning_latched is True
    assert window._commit_warning_widget.isHidden() is False

    # Charge drops back below the threshold → warning latches (stays visible).
    window.ingest_samples([under])
    window.update_tick()
    assert window._commit_warning_latched is True
    assert window._commit_warning_widget.isHidden() is False

    # User clears → dismissed, and it stays dismissed while the charge remains low.
    window._clear_commit_warning()
    assert window._commit_warning_latched is False
    assert window._commit_warning_widget.isHidden() is True

    window.ingest_samples([_commit_sample(now + 1.0, 10.0)])
    window.update_tick()
    assert window._commit_warning_latched is False
    assert window._commit_warning_widget.isHidden() is True


def test_coverage_tab_paint_forced(qtbot):
    """Force a real paintEvent on the coverage chart with data."""
    tab = CoverageTab()
    qtbot.addWidget(tab)
    now = time.time()

    guid = "cov-test-guid"
    infos = [
        PytestProcessInfo(guid, "tests/test_a.py", None, PyTestFlyExitCode.NONE, "", now - 10),
        PytestProcessInfo(guid, "tests/test_a.py", 1, PyTestFlyExitCode.NONE, "", now - 8),
        PytestProcessInfo(guid, "tests/test_a.py", 1, PyTestFlyExitCode.OK, "", now - 5),
    ]
    tick = build_tick_data(infos)
    tick.coverage_history = [(now - 5, 0.25), (now - 2, 0.50), (now, 0.75)]
    tick.covered_lines = 150
    tick.total_lines = 200
    tab.update_tick(tick)

    _force_paint(tab, 800, 400)
    _force_paint(tab.chart, 800, 400)


def test_coverage_tab_paint_empty_forced(qtbot):
    tab = CoverageTab()
    qtbot.addWidget(tab)
    tick = build_tick_data([])
    tab.update_tick(tick)
    _force_paint(tab, 800, 400)
    _force_paint(tab.chart, 800, 400)


def test_control_window_filter_for_resume(qtbot):
    """RESUME mode drops tests whose prior run passed; other modes keep them."""
    data_dir = get_temp_dir("test_control_window_filter_resume")
    cw = ControlWindow(None, data_dir)
    qtbot.addWidget(cw)

    tests = [
        ScheduledTest(node_id="tests/test_a.py", singleton=False, duration=None, coverage=None),
        ScheduledTest(node_id="tests/test_b.py", singleton=False, duration=None, coverage=None),
        ScheduledTest(node_id="tests/test_c.py", singleton=False, duration=None, coverage=None),
    ]
    prior = [
        PytestProcessInfo("g", "tests/test_a.py", 1, PyTestFlyExitCode.OK, "", 1.0),
        PytestProcessInfo("g", "tests/test_b.py", 2, PyTestFlyExitCode.TESTS_FAILED, "", 1.0),
    ]

    remaining = cw._filter_for_resume(tests, prior, RunMode.RESUME)
    names = [t.node_id for t in remaining]
    assert "tests/test_a.py" not in names  # previously passed — skip
    assert "tests/test_b.py" in names  # failed — must rerun
    assert "tests/test_c.py" in names  # never ran — must rerun

    # RESTART ignores prior results
    assert cw._filter_for_resume(tests, prior, RunMode.RESTART) == tests


def test_control_window_resolve_check_mode(qtbot):
    """CHECK mode collapses to RESUME when fingerprints match, RESTART otherwise."""
    data_dir = get_temp_dir("test_control_window_check")
    cw = ControlWindow(None, data_dir)
    qtbot.addWidget(cw)

    # No prior PUT fingerprint → RESTART.
    assert cw._resolve_check_mode([]) == RunMode.RESTART

    class _FakePut:
        def fingerprint(self):
            return "fp-current"

    cw.put_version_info = _FakePut()

    matching = [PytestProcessInfo("g", "t.py", 1, PyTestFlyExitCode.OK, "", 1.0, put_fingerprint="fp-current")]
    assert cw._resolve_check_mode(matching) == RunMode.RESUME

    mismatch = [PytestProcessInfo("g", "t.py", 1, PyTestFlyExitCode.OK, "", 1.0, put_fingerprint="fp-old")]
    assert cw._resolve_check_mode(mismatch) == RunMode.RESTART


def test_fly_app_main_window_constructs(app):
    """FlyAppMainWindow should instantiate all tabs and its background monitor."""
    data_dir = get_temp_dir("test_fly_app_main_window")

    window = FlyAppMainWindow(data_dir)
    try:
        window.timer.stop()

        assert window.run_tab is not None
        assert window.graph_tab is not None
        assert window.table_tab is not None
        assert window.coverage_tab is not None
        assert window.configuration is not None
        assert window.about is not None
        assert window._coverage_tracker is not None
        assert window._system_monitor.is_alive()

        window._update_tick()
    finally:
        window.timer.stop()
        window._system_monitor.request_stop()
        window._system_monitor.join(5.0)
        if window._system_monitor.is_alive():
            window._system_monitor.terminate()
            window._system_monitor.join(5.0)
        # Delete the widget directly — avoids qtbot's close() which would invoke
        # closeEvent (persisting preferences and potentially blocking on cleanup).
        window.deleteLater()


def test_window_geometry_round_trips_without_drift(app):
    """Reopening the app restores to a stable geometry — no per-launch drift.

    Regression for the frameGeometry-save vs setGeometry-restore mismatch (one set the outer
    frame, the other the client area), which shifted and grew the window on every relaunch.
    Exercises the real save (closeEvent) and restore (__init__) paths; geometry serialization
    converges after the first reopen, so two successive reopens must produce identical geometry.
    """
    data_dir = get_temp_dir("test_window_geometry_drift")

    class _Event:
        def accept(self):
            pass

    def open_and_close(set_rect: QRect | None = None) -> str:
        window = FlyAppMainWindow(data_dir)
        window.timer.stop()
        if set_rect is not None:
            window.setGeometry(set_rect)
        window.closeEvent(_Event())  # persists window_geometry and stops the system monitor
        if window._system_monitor.is_alive():
            window._system_monitor.terminate()
            window._system_monitor.join(5.0)
        window.deleteLater()
        return get_pref().window_geometry

    open_and_close(QRect(140, 110, 900, 600))  # first launch: set + save a known geometry
    geometry_after_first_reopen = open_and_close()  # restore it, then re-save
    geometry_after_second_reopen = open_and_close()  # restore again, re-save

    assert geometry_after_first_reopen != ""
    assert geometry_after_first_reopen == geometry_after_second_reopen  # stable: no drift
