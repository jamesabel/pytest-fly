"""Additional widget tests targeting paint paths and integration points."""

import time

from PySide6.QtCore import QSize

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


def test_control_window_reorder_failed_first(qtbot):
    """_reorder_failed_first puts previously-failed tests ahead of previously-passed ones."""
    data_dir = get_temp_dir("test_control_window_reorder")
    cw = ControlWindow(None, data_dir)
    qtbot.addWidget(cw)

    tests = [
        ScheduledTest(node_id="tests/test_pass.py", singleton=False, duration=None, coverage=None),
        ScheduledTest(node_id="tests/test_fail.py", singleton=False, duration=None, coverage=None),
        ScheduledTest(node_id="tests/test_singleton.py", singleton=True, duration=None, coverage=None),
    ]
    prior = [
        PytestProcessInfo("g", "tests/test_pass.py", 1, PyTestFlyExitCode.OK, "", 1.0),
        PytestProcessInfo("g", "tests/test_fail.py", 2, PyTestFlyExitCode.TESTS_FAILED, "", 1.0),
    ]

    ordered = cw._reorder_failed_first(tests, prior)
    node_ids = [t.node_id for t in ordered]
    # Previously-failed must come before previously-passed within non-singleton group.
    assert node_ids.index("tests/test_fail.py") < node_ids.index("tests/test_pass.py")
    # Singletons stay at the end.
    assert node_ids[-1] == "tests/test_singleton.py"


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
