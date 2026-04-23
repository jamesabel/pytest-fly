"""
Tests that verify the GUI tabs display correct data when given TickData.
"""

import time
from pathlib import Path

from pytest_fly.db import PytestProcessInfoDB
from pytest_fly.gui.about_tab.about import About
from pytest_fly.gui.about_tab.project_info import get_project_info
from pytest_fly.gui.configuration_tab.configuration import Configuration
from pytest_fly.gui.coverage_tab import CoverageTab
from pytest_fly.gui.graph_tab.graph_tab import GraphTab
from pytest_fly.gui.graph_tab.progress_bar import PytestProgressBar
from pytest_fly.gui.graph_tab.time_axis import TimeAxisWidget
from pytest_fly.gui.gui_main import build_tick_data
from pytest_fly.gui.gui_util import compute_average_parallelism
from pytest_fly.gui.run_tab.control_pushbutton import ControlButton
from pytest_fly.gui.run_tab.control_window import ControlWindow
from pytest_fly.gui.run_tab.parallelism_control_box import ParallelismControlBox
from pytest_fly.gui.run_tab.run_mode_control_box import RunModeControlBox
from pytest_fly.gui.run_tab.run_tab import RunTab
from pytest_fly.gui.run_tab.status_window import StatusWindow
from pytest_fly.gui.run_tab.view_coverage import ViewCoverage
from pytest_fly.gui.table_tab.table_tab import TableTab
from pytest_fly.guid import generate_uuid
from pytest_fly.interfaces import PyTestFlyExitCode, PytestProcessInfo, PytestRunnerState, ScheduledTest
from pytest_fly.pytest_runner.pytest_runner import PytestRunner, PytestRunState

from .paths import get_temp_dir


def _make_process_info(run_guid, name, pid, exit_code, output=None, time_stamp=None, cpu_percent=None, memory_percent=None):
    """Helper to create a PytestProcessInfo with sensible defaults."""
    return PytestProcessInfo(
        run_guid=run_guid,
        name=name,
        pid=pid,
        exit_code=exit_code,
        output=output,
        time_stamp=time_stamp or time.time(),
        cpu_percent=cpu_percent,
        memory_percent=memory_percent,
    )


def _make_tick_data_empty():
    """Create a TickData with no process info (empty run)."""
    return build_tick_data([])


def _make_tick_data_with_tests():
    """Create a TickData with a mix of test states for display testing."""
    guid = "test-guid-display"
    now = time.time()

    infos = [
        # test_a: QUEUED then RUNNING then PASS
        _make_process_info(guid, "tests/test_a.py", None, PyTestFlyExitCode.NONE, time_stamp=now - 10),
        _make_process_info(guid, "tests/test_a.py", 1001, PyTestFlyExitCode.NONE, time_stamp=now - 9),
        _make_process_info(guid, "tests/test_a.py", 1001, PyTestFlyExitCode.OK, output="1 passed", time_stamp=now - 5, cpu_percent=50.0, memory_percent=1.5),
        # test_b: QUEUED then RUNNING then FAIL
        _make_process_info(guid, "tests/test_b.py", None, PyTestFlyExitCode.NONE, time_stamp=now - 10),
        _make_process_info(guid, "tests/test_b.py", 1002, PyTestFlyExitCode.NONE, time_stamp=now - 8),
        _make_process_info(guid, "tests/test_b.py", 1002, PyTestFlyExitCode.TESTS_FAILED, output="1 failed", time_stamp=now - 3, cpu_percent=80.0, memory_percent=2.0),
        # test_c: QUEUED only
        _make_process_info(guid, "tests/test_c.py", None, PyTestFlyExitCode.NONE, time_stamp=now - 10),
    ]
    return build_tick_data(infos)


# ---------------------------------------------------------------------------
# StatusWindow tests
# ---------------------------------------------------------------------------


def test_status_window_empty(app):
    """StatusWindow should display 'Calculating...' when there is no data."""
    window = StatusWindow(None)
    tick = _make_tick_data_empty()
    window.update_tick(tick)

    text = window.status_widget.toPlainText()
    assert "Calculating..." in text


def test_status_window_with_data(app):
    """StatusWindow should display test counts and pass rate for real data."""
    window = StatusWindow(None)
    tick = _make_tick_data_with_tests()
    window.update_tick(tick)

    text = window.status_widget.toPlainText()
    assert "3 tests" in text
    # 1 pass out of 2 completed (test_a passed, test_b failed, test_c queued)
    pass_rate_text = window.pass_rate_label.text()
    assert "Pass rate:" in pass_rate_text
    assert "1/2" in pass_rate_text
    # State counts should be present
    assert "Pass: 1" in text
    assert "Fail: 1" in text
    assert "Queued: 1" in text


# ---------------------------------------------------------------------------
# TableTab tests
# ---------------------------------------------------------------------------


def test_table_tab_empty(app):
    """TableTab should have zero rows for empty data."""
    table = TableTab(get_temp_dir("table_tab"))
    tick = _make_tick_data_empty()
    table.update_tick(tick)

    assert table.table_widget.rowCount() == 0


def test_table_tab_with_data(app):
    """TableTab should show one row per test with correct state text."""
    table = TableTab(get_temp_dir("table_tab"))
    tick = _make_tick_data_with_tests()
    table.update_tick(tick)

    assert table.table_widget.rowCount() == 3

    # Collect all displayed test names and states
    displayed = {}
    for row in range(table.table_widget.rowCount()):
        name_item = table.table_widget.item(row, 0)  # NAME column
        state_item = table.table_widget.item(row, 1)  # STATE column
        assert name_item is not None, f"row {row} NAME is None"
        assert state_item is not None, f"row {row} STATE is None"
        displayed[name_item.text()] = state_item.text()

    assert displayed["tests/test_a.py"] == PytestRunnerState.PASS.value
    assert displayed["tests/test_b.py"] == PytestRunnerState.FAIL.value
    assert displayed["tests/test_c.py"] == PytestRunnerState.QUEUED.value


def test_table_tab_per_test_coverage(app):
    """TableTab should display per-test coverage when per_test_coverage is populated."""
    table = TableTab(get_temp_dir("table_tab"))
    tick = _make_tick_data_with_tests()
    tick.per_test_coverage = {"tests/test_a.py": 0.123, "tests/test_b.py": 0.456}
    table.update_tick(tick)

    # Collect coverage values by test name
    coverage_by_name = {}
    for row in range(table.table_widget.rowCount()):
        name_item = table.table_widget.item(row, 0)
        cov_item = table.table_widget.item(row, 5)  # COVERAGE column
        assert cov_item is not None, f"row {row} COVERAGE item is None"
        coverage_by_name[name_item.text()] = cov_item.text()

    assert coverage_by_name["tests/test_a.py"] == "12.3%"
    assert coverage_by_name["tests/test_b.py"] == "45.6%"
    assert coverage_by_name["tests/test_c.py"] == ""  # queued, no coverage yet


def test_per_test_coverage_not_greater_than_combined(app):
    """Per-test coverage values must not exceed the combined coverage percentage."""
    tick = _make_tick_data_with_tests()
    combined_pct = 0.52
    tick.coverage_history = [(time.time(), combined_pct)]
    # Simulate per-test values that are valid (each <= combined)
    tick.per_test_coverage = {"tests/test_a.py": 0.35, "tests/test_b.py": 0.40}

    for test_name, pct in tick.per_test_coverage.items():
        assert pct <= combined_pct, f"{test_name} coverage {pct:.1%} exceeds combined {combined_pct:.1%}"

    # Verify the table displays them correctly
    table = TableTab(get_temp_dir("table_tab"))
    table.update_tick(tick)
    for row in range(table.table_widget.rowCount()):
        name_item = table.table_widget.item(row, 0)
        cov_item = table.table_widget.item(row, 5)
        cov_text = cov_item.text()
        if cov_text:
            # Parse back the percentage and verify it's <= combined
            pct_value = float(cov_text.rstrip("%")) / 100.0
            assert pct_value <= combined_pct + 0.001, f"{name_item.text()} shows {cov_text} which exceeds combined {combined_pct:.1%}"


def test_table_tab_updates_on_second_tick(app):
    """TableTab should reflect new state when update_tick is called again."""
    table = TableTab(get_temp_dir("table_tab"))
    guid = "test-guid-update"
    now = time.time()

    # First tick: test_a is QUEUED
    infos_1 = [_make_process_info(guid, "tests/test_a.py", None, PyTestFlyExitCode.NONE, time_stamp=now)]
    tick_1 = build_tick_data(infos_1)
    table.update_tick(tick_1)

    state_1 = table.table_widget.item(0, 1).text()
    assert state_1 == PytestRunnerState.QUEUED.value

    # Second tick: test_a transitions to PASS
    infos_2 = [
        _make_process_info(guid, "tests/test_a.py", None, PyTestFlyExitCode.NONE, time_stamp=now),
        _make_process_info(guid, "tests/test_a.py", 2001, PyTestFlyExitCode.NONE, time_stamp=now + 1),
        _make_process_info(guid, "tests/test_a.py", 2001, PyTestFlyExitCode.OK, output="1 passed", time_stamp=now + 5),
    ]
    tick_2 = build_tick_data(infos_2)
    table.update_tick(tick_2)

    state_2 = table.table_widget.item(0, 1).text()
    assert state_2 == PytestRunnerState.PASS.value


def test_table_tab_last_pass_columns(app):
    """TableTab should display last pass start time and duration from last_pass_data."""
    from pytest_fly.gui.table_tab.table_tab import Columns

    table = TableTab(get_temp_dir("table_tab"))
    tick = _make_tick_data_with_tests()
    now = time.time()
    tick.last_pass_data = {
        "tests/test_a.py": (now - 3600, 4.5),  # passed 1 hour ago, took 4.5s
    }
    table.update_tick(tick)

    assert table.table_widget.columnCount() == len(Columns)

    # Collect last-pass data by test name
    last_pass_by_name = {}
    for row in range(table.table_widget.rowCount()):
        name_item = table.table_widget.item(row, Columns.NAME.value)
        start_item = table.table_widget.item(row, Columns.LAST_PASS_START.value)
        dur_item = table.table_widget.item(row, Columns.LAST_PASS_DURATION.value)
        assert start_item is not None
        assert dur_item is not None
        last_pass_by_name[name_item.text()] = (start_item.text(), dur_item.text())

    # test_a has last-pass data
    start_text, dur_text = last_pass_by_name["tests/test_a.py"]
    assert start_text != ""  # should have a formatted datetime
    assert "4" in dur_text  # should contain "4" from "4.5 seconds"

    # test_b and test_c have no last-pass data
    assert last_pass_by_name["tests/test_b.py"] == ("", "")
    assert last_pass_by_name["tests/test_c.py"] == ("", "")


def test_table_tab_double_click_name_sorts(app):
    """Double-clicking the Name header should sort rows alphabetically without crashing.

    Regression test for the access violation that occurred when _SortableItem.__lt__
    fell through to super().__lt__ for columns without a numeric sort key.
    """
    from pytest_fly.gui.table_tab.table_tab import Columns

    table = TableTab(get_temp_dir("table_tab"))
    guid = "test-guid-sort"
    now = time.time()

    # Three tests whose alphabetical order differs from their insertion order,
    # so a successful sort is observable.
    infos = [
        _make_process_info(guid, "tests/test_zebra.py", None, PyTestFlyExitCode.NONE, time_stamp=now),
        _make_process_info(guid, "tests/test_apple.py", None, PyTestFlyExitCode.NONE, time_stamp=now),
        _make_process_info(guid, "tests/test_mango.py", None, PyTestFlyExitCode.NONE, time_stamp=now),
    ]
    tick = build_tick_data(infos)
    table.update_tick(tick)

    # Simulate a double-click on the Name column header via the wired signal.
    table.table_widget.horizontalHeader().sectionDoubleClicked.emit(Columns.NAME.value)

    names_ascending = [table.table_widget.item(r, Columns.NAME.value).text() for r in range(table.table_widget.rowCount())]
    assert names_ascending == ["tests/test_apple.py", "tests/test_mango.py", "tests/test_zebra.py"]
    assert table._sort_column == Columns.NAME.value
    # _row_by_name must be rebuilt to match the new visual order
    assert table._row_by_name["tests/test_apple.py"] == 0
    assert table._row_by_name["tests/test_mango.py"] == 1
    assert table._row_by_name["tests/test_zebra.py"] == 2

    # Double-click again → descending
    table.table_widget.horizontalHeader().sectionDoubleClicked.emit(Columns.NAME.value)
    names_descending = [table.table_widget.item(r, Columns.NAME.value).text() for r in range(table.table_widget.rowCount())]
    assert names_descending == ["tests/test_zebra.py", "tests/test_mango.py", "tests/test_apple.py"]
    assert table._row_by_name["tests/test_zebra.py"] == 0
    assert table._row_by_name["tests/test_apple.py"] == 2

    # Subsequent update_tick must preserve the active sort
    table.update_tick(tick)
    names_after_update = [table.table_widget.item(r, Columns.NAME.value).text() for r in range(table.table_widget.rowCount())]
    assert names_after_update == ["tests/test_zebra.py", "tests/test_mango.py", "tests/test_apple.py"]


# ---------------------------------------------------------------------------
# GraphTab tests
# ---------------------------------------------------------------------------


def test_graph_tab_empty(app):
    """GraphTab should have no progress bars for empty data."""
    graph = GraphTab()
    tick = _make_tick_data_empty()
    graph.update_tick(tick)

    assert len(graph.progress_bars) == 0


def test_graph_tab_creates_bars(app):
    """GraphTab should create one progress bar per test."""
    graph = GraphTab()
    tick = _make_tick_data_with_tests()
    graph.update_tick(tick)

    assert len(graph.progress_bars) == 3
    assert "tests/test_a.py" in graph.progress_bars
    assert "tests/test_b.py" in graph.progress_bars
    assert "tests/test_c.py" in graph.progress_bars


def test_graph_tab_reuses_bars(app):
    """GraphTab should reuse existing bars on subsequent ticks, not create new ones."""
    graph = GraphTab()
    tick = _make_tick_data_with_tests()

    graph.update_tick(tick)
    first_bars = dict(graph.progress_bars)

    graph.update_tick(tick)
    assert len(graph.progress_bars) == 3
    # Same widget objects, not new ones
    for name, bar in graph.progress_bars.items():
        assert bar is first_bars[name], f"bar for {name} was recreated instead of reused"


# ---------------------------------------------------------------------------
# CoverageTab tests
# ---------------------------------------------------------------------------


def test_coverage_tab_empty(app):
    """CoverageTab should render without error when there is no coverage data."""
    from pytest_fly.gui.coverage_tab import CoverageTab

    tab = CoverageTab()
    tick = _make_tick_data_empty()
    tab.update_tick(tick)

    assert tab.chart._coverage_history == []


def test_coverage_tab_with_data(app):
    """CoverageTab should store coverage history and values should increase over time."""
    from pytest_fly.gui.coverage_tab import CoverageTab

    tab = CoverageTab()
    tick = _make_tick_data_with_tests()
    now = time.time()
    tick.coverage_history = [(now - 5, 0.25), (now - 2, 0.40), (now, 0.52)]
    tab.update_tick(tick)

    assert tab.chart._coverage_history == tick.coverage_history
    assert len(tab.chart._coverage_history) == 3
    # Coverage should be monotonically non-decreasing (each test adds coverage)
    for i in range(1, len(tab.chart._coverage_history)):
        assert tab.chart._coverage_history[i][1] >= tab.chart._coverage_history[i - 1][1]


def test_coverage_tab_updates(app):
    """CoverageTab should reflect new data when update_tick is called again."""
    from pytest_fly.gui.coverage_tab import CoverageTab

    tab = CoverageTab()
    now = time.time()

    # First tick: one data point
    tick_1 = _make_tick_data_with_tests()
    tick_1.coverage_history = [(now - 5, 0.30)]
    tab.update_tick(tick_1)
    assert len(tab.chart._coverage_history) == 1

    # Second tick: two data points
    tick_2 = _make_tick_data_with_tests()
    tick_2.coverage_history = [(now - 5, 0.30), (now, 0.65)]
    tab.update_tick(tick_2)
    assert len(tab.chart._coverage_history) == 2
    assert tab.chart._coverage_history[-1][1] == 0.65


def test_coverage_tab_status_indicator(app):
    """CoverageTab should show running/complete status based on test states."""
    from pytest_fly.gui.coverage_tab import CoverageTab

    tab = CoverageTab()

    # With running and queued tests: shows "Running"
    tick = _make_tick_data_with_tests()  # has PASS, FAIL, and QUEUED tests
    tab.update_tick(tick)
    assert "Running" in tab.chart._status_text

    # All tests completed (no QUEUED or RUNNING)
    guid = "test-guid-complete"
    now = time.time()
    infos = [
        _make_process_info(guid, "tests/test_a.py", None, PyTestFlyExitCode.NONE, time_stamp=now - 5),
        _make_process_info(guid, "tests/test_a.py", 1001, PyTestFlyExitCode.NONE, time_stamp=now - 4),
        _make_process_info(guid, "tests/test_a.py", 1001, PyTestFlyExitCode.OK, output="1 passed", time_stamp=now - 1),
    ]
    tick_done = build_tick_data(infos)
    tab.update_tick(tick_done)
    assert "Complete" in tab.chart._status_text


# ---------------------------------------------------------------------------
# ControlButton tests
# ---------------------------------------------------------------------------


def test_control_button(qtbot):
    """ControlButton should set text and enabled state."""
    btn = ControlButton(None, "Run", True)
    qtbot.addWidget(btn)
    assert btn.text() == "Run"
    assert btn.isEnabled()

    btn2 = ControlButton(None, "Stop", False)
    qtbot.addWidget(btn2)
    assert btn2.text() == "Stop"
    assert not btn2.isEnabled()


# ---------------------------------------------------------------------------
# RunModeControlBox tests
# ---------------------------------------------------------------------------


def test_run_mode_control_box(qtbot):
    """RunModeControlBox should initialize with radio buttons available."""
    box = RunModeControlBox(None)
    qtbot.addWidget(box)
    # Verify widgets exist and are functional
    assert box.run_mode_restart is not None
    assert box.run_mode_resume is not None


def test_run_mode_control_box_toggle(qtbot):
    """Toggling run mode radio buttons should update preferences."""
    box = RunModeControlBox(None)
    qtbot.addWidget(box)
    box.run_mode_resume.setChecked(True)
    box.update_preferences()
    box.run_mode_restart.setChecked(True)
    box.update_preferences()


# ---------------------------------------------------------------------------
# ParallelismControlBox tests
# ---------------------------------------------------------------------------


def test_parallelism_control_box(qtbot):
    """ParallelismControlBox should initialize with one option checked."""
    box = ParallelismControlBox(None)
    qtbot.addWidget(box)
    assert box.parallelism_serial.isChecked() or box.parallelism_parallel.isChecked()


def test_parallelism_control_box_toggle(qtbot):
    """Toggling parallelism radio buttons should update preferences."""
    box = ParallelismControlBox(None)
    qtbot.addWidget(box)
    box.parallelism_parallel.setChecked(True)
    box.update_preferences()
    assert "Parallel" in box.parallelism_parallel.text()


# ---------------------------------------------------------------------------
# Configuration tests
# ---------------------------------------------------------------------------


def test_configuration_init(qtbot):
    """Configuration tab should instantiate with all widgets."""
    config = Configuration()
    qtbot.addWidget(config)
    assert config.verbose_checkbox is not None
    assert config.processes_lineedit.text().isnumeric()
    assert len(config.refresh_rate_lineedit.text()) > 0


def test_configuration_update_methods(qtbot):
    """Configuration update callbacks should not raise."""
    config = Configuration()
    qtbot.addWidget(config)
    config.update_verbose()
    config.update_processes("4")
    config.update_processes("not_a_number")  # should handle gracefully
    config.update_refresh_rate("2.0")
    config.update_refresh_rate("invalid")  # should handle ValueError
    config.update_utilization_high_threshold("0.9")
    config.update_utilization_low_threshold("0.4")
    config.update_utilization_high_threshold("invalid")  # ValueError path
    config.update_utilization_low_threshold("invalid")  # ValueError path


# ---------------------------------------------------------------------------
# About / ProjectInfo tests
# ---------------------------------------------------------------------------


def test_project_info():
    """get_project_info should return valid project metadata."""
    info = get_project_info()
    assert info.application_name != "Unknown"
    assert info.version != "Unknown"
    # covers __str__
    s = str(info)
    assert info.application_name in s
    assert info.version in s


def test_about(qtbot):
    """About tab should load project and platform info in background."""
    about = About(None)
    qtbot.addWidget(about)
    qtbot.waitUntil(lambda: not about.thread.isRunning(), timeout=10000)
    text = about.about_box.toPlainText()
    assert len(text) > 10


# ---------------------------------------------------------------------------
# RunTab / ControlWindow tests
# ---------------------------------------------------------------------------


def test_run_tab(qtbot):
    """RunTab should instantiate and accept tick data."""
    data_dir = get_temp_dir("test_run_tab")
    tab = RunTab(None, data_dir)
    qtbot.addWidget(tab)
    tick = _make_tick_data_with_tests()
    tab.update_tick(tick)


def test_control_window_update(qtbot):
    """ControlWindow.update() should enable Run and disable Stop/Force Stop when idle."""
    data_dir = get_temp_dir("test_control_window")
    cw = ControlWindow(None, data_dir)
    qtbot.addWidget(cw)
    cw.update()
    assert cw.run_button.isEnabled()
    assert not cw.stop_button.isEnabled()
    assert not cw.force_stop_button.isEnabled()


# ---------------------------------------------------------------------------
# ViewCoverage tests
# ---------------------------------------------------------------------------


def test_view_coverage_missing_dir():
    """ViewCoverage.view() should not crash when directory doesn't exist."""
    vc = ViewCoverage(Path("nonexistent_dir_xyz_12345"))
    vc.view()  # should log warning, not raise


# ---------------------------------------------------------------------------
# StatusWindow ETA and coverage branches
# ---------------------------------------------------------------------------


def test_status_window_with_eta(app):
    """StatusWindow should display estimated remaining time when prior durations are available."""
    window = StatusWindow(None)
    tick = _make_tick_data_with_tests()
    tick.prior_durations = {"tests/test_a.py": 5.0, "tests/test_c.py": 3.0}
    tick.num_processes = 2
    window.update_tick(tick)
    text = window.status_widget.toPlainText()
    assert "Estimated remaining" in text


def test_status_window_with_coverage(app):
    """StatusWindow should display coverage percentage with line counts."""
    window = StatusWindow(None)
    tick = _make_tick_data_with_tests()
    tick.coverage_history = [(time.time() - 5, 0.30), (time.time(), 0.52)]
    tick.covered_lines = 260
    tick.total_lines = 500
    window.update_tick(tick)
    text = window.status_widget.toPlainText()
    # Should show the latest value (52.0%), not the first (30.0%)
    assert "Coverage: 52.0%" in text
    assert "260/500 lines" in text
    assert "30.0%" not in text


def test_average_parallelism_calculation(app):
    """compute_average_parallelism should return correct value for overlapping tests."""
    tick = _make_tick_data_with_tests()
    # test_a: started at now-9, ended at now-5 → 4s
    # test_b: started at now-8, ended at now-3 → 5s
    # test_c: queued only → 0s
    # wall clock: (now-9) to (now-3) = 6s
    # avg parallelism = (4+5)/6 = 1.5
    assert tick.average_parallelism is not None
    assert abs(tick.average_parallelism - 1.5) < 0.01


def test_average_parallelism_empty():
    """compute_average_parallelism should return None for empty data."""
    assert compute_average_parallelism({}) is None


def test_status_window_shows_parallelism(app):
    """StatusWindow should display average parallelism when available."""
    window = StatusWindow(None)
    tick = _make_tick_data_with_tests()
    window.update_tick(tick)
    text = window.status_widget.toPlainText()
    assert "Avg parallelism:" in text
    assert "1.5x" in text


def test_coverage_consistent_across_all_views(app):
    """Coverage values should be consistent across Status pane and Coverage tab."""
    now = time.time()
    tick = _make_tick_data_with_tests()
    combined_pct = 0.52
    tick.coverage_history = [(now - 5, 0.30), (now, combined_pct)]
    tick.covered_lines = 260
    tick.total_lines = 500

    # Status pane shows combined with line counts
    status = StatusWindow(None)
    status.update_tick(tick)
    status_text = status.status_widget.toPlainText()
    assert "Coverage: 52.0%" in status_text
    assert "260/500 lines" in status_text

    # Coverage tab chart has the history
    coverage_tab = CoverageTab()
    coverage_tab.update_tick(tick)
    assert coverage_tab.chart._coverage_history[-1][1] == combined_pct


# ---------------------------------------------------------------------------
# ProgressBar paint tests
# ---------------------------------------------------------------------------


def test_progress_bar_queued(qtbot):
    """PytestProgressBar should render a queued test without errors."""
    guid = "test-guid-bar"
    now = time.time()
    infos = [_make_process_info(guid, "tests/test_a.py", None, PyTestFlyExitCode.NONE, time_stamp=now)]
    run_state = PytestRunState(infos)
    bar = PytestProgressBar(infos, now - 1, now + 1, run_state)
    qtbot.addWidget(bar)
    bar.show()
    bar.repaint()


def test_progress_bar_pass(qtbot):
    """PytestProgressBar should render a passed test with bar color."""
    guid = "test-guid-bar-pass"
    now = time.time()
    infos = [
        _make_process_info(guid, "tests/test_a.py", None, PyTestFlyExitCode.NONE, time_stamp=now - 5),
        _make_process_info(guid, "tests/test_a.py", 1001, PyTestFlyExitCode.NONE, time_stamp=now - 4),
        _make_process_info(guid, "tests/test_a.py", 1001, PyTestFlyExitCode.OK, output="1 passed", time_stamp=now - 1),
    ]
    run_state = PytestRunState(infos)
    bar = PytestProgressBar(infos, now - 5, now, run_state)
    qtbot.addWidget(bar)
    bar.show()
    bar.repaint()


def test_progress_bar_update(qtbot):
    """PytestProgressBar.update_pytest_process_info should accept new data."""
    guid = "test-guid-bar-update"
    now = time.time()
    infos = [_make_process_info(guid, "tests/test_a.py", None, PyTestFlyExitCode.NONE, time_stamp=now)]
    run_state = PytestRunState(infos)
    bar = PytestProgressBar(infos, now - 1, now + 1, run_state)
    qtbot.addWidget(bar)

    # Update with completed state
    infos2 = infos + [
        _make_process_info(guid, "tests/test_a.py", 1001, PyTestFlyExitCode.NONE, time_stamp=now + 1),
        _make_process_info(guid, "tests/test_a.py", 1001, PyTestFlyExitCode.OK, output="1 passed", time_stamp=now + 3),
    ]
    run_state2 = PytestRunState(infos2)
    bar.update_pytest_process_info(infos2, now - 1, now + 3, run_state2)
    bar.repaint()


# ---------------------------------------------------------------------------
# TimeAxisWidget paint tests
# ---------------------------------------------------------------------------


def test_time_axis_widget_paint(qtbot):
    """TimeAxisWidget should render tick marks and labels."""
    widget = TimeAxisWidget()
    qtbot.addWidget(widget)
    widget.update_time_window(1000.0, 1010.0)
    widget.show()
    widget.repaint()


def test_time_axis_widget_no_data(qtbot):
    """TimeAxisWidget should handle None timestamps gracefully."""
    widget = TimeAxisWidget()
    qtbot.addWidget(widget)
    widget.update_time_window(None, None)
    widget.show()
    widget.repaint()


# ---------------------------------------------------------------------------
# CoverageTab paint tests
# ---------------------------------------------------------------------------


def test_coverage_tab_paint_with_data(qtbot):
    """CoverageTab chart should render the step-function line when data is present."""
    tab = CoverageTab()
    qtbot.addWidget(tab)
    now = time.time()
    tick = _make_tick_data_with_tests()
    tick.coverage_history = [(now - 5, 0.3), (now - 2, 0.55), (now, 0.7)]
    tab.update_tick(tick)
    tab.chart.show()
    tab.chart.repaint()


def test_coverage_tab_paint_empty(qtbot):
    """CoverageTab chart should render 'Waiting' message with no data."""
    tab = CoverageTab()
    qtbot.addWidget(tab)
    tick = _make_tick_data_empty()
    tab.update_tick(tick)
    tab.chart.show()
    tab.chart.repaint()


def test_coverage_tab_paint_single_point(qtbot):
    """CoverageTab chart should handle a single coverage data point."""
    tab = CoverageTab()
    qtbot.addWidget(tab)
    now = time.time()
    tick = _make_tick_data_with_tests()
    tick.coverage_history = [(now, 0.42)]
    tab.update_tick(tick)
    tab.chart.show()
    tab.chart.repaint()


# ---------------------------------------------------------------------------
# Integration test: real runner → DB → TickData → GUI tabs
# ---------------------------------------------------------------------------


def test_full_pipeline(app):
    """Run a real test through PytestRunner, query DB, build TickData, and verify all tabs display data."""
    data_dir = get_temp_dir("test_full_pipeline")
    run_guid = generate_uuid()

    scheduled_tests = [ScheduledTest(node_id="tests/test_no_operation.py", singleton=False, duration=None, coverage=None)]
    runner = PytestRunner(run_guid, scheduled_tests, number_of_processes=1, data_dir=data_dir, update_rate=3.0)
    runner.start()
    runner.join(30.0)

    with PytestProcessInfoDB(data_dir) as db:
        process_infos = db.query(run_guid)

    assert len(process_infos) >= 2, f"expected at least 2 DB records, got {len(process_infos)}"

    tick = build_tick_data(process_infos)

    # Verify TickData shape
    assert len(tick.infos_by_name) == 1
    assert "tests/test_no_operation.py" in tick.infos_by_name
    assert "tests/test_no_operation.py" in tick.run_states

    run_state = tick.run_states["tests/test_no_operation.py"]
    assert run_state.get_state() == PytestRunnerState.PASS

    # StatusWindow
    status = StatusWindow(None)
    status.update_tick(tick)
    status_text = status.status_widget.toPlainText()
    assert "1 tests" in status_text
    assert "Pass: 1" in status_text

    # TableTab
    table = TableTab(get_temp_dir("table_tab"))
    table.update_tick(tick)
    assert table.table_widget.rowCount() == 1
    assert table.table_widget.item(0, 0).text() == "tests/test_no_operation.py"
    assert table.table_widget.item(0, 1).text() == PytestRunnerState.PASS.value

    # GraphTab
    graph = GraphTab()
    graph.update_tick(tick)
    assert len(graph.progress_bars) == 1
    assert "tests/test_no_operation.py" in graph.progress_bars
