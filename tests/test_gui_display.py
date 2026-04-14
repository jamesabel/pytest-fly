"""
Tests that verify the GUI tabs display correct data when given TickData.
"""

import time

from pytest_fly.db import PytestProcessInfoDB
from pytest_fly.gui.gui_main import build_tick_data
from pytest_fly.gui.run_tab.status_window import StatusWindow
from pytest_fly.gui.table_tab.table_tab import TableTab
from pytest_fly.gui.graph_tab.graph_tab import GraphTab
from pytest_fly.interfaces import PytestProcessInfo, PyTestFlyExitCode, PytestRunnerState, ScheduledTest
from pytest_fly.pytest_runner.pytest_runner import PytestRunner
from pytest_fly.guid import generate_uuid

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
    """StatusWindow should display 'Tests not yet run' when there is no data."""
    window = StatusWindow(None)
    tick = _make_tick_data_empty()
    window.update_tick(tick)

    text = window.status_widget.toPlainText()
    assert "Tests not yet run" in text


def test_status_window_with_data(app):
    """StatusWindow should display test counts and pass rate for real data."""
    window = StatusWindow(None)
    tick = _make_tick_data_with_tests()
    window.update_tick(tick)

    text = window.status_widget.toPlainText()
    assert "3 tests" in text
    # 1 pass out of 2 completed (test_a passed, test_b failed, test_c queued)
    assert "Pass rate:" in text
    assert "1/2" in text
    # State counts should be present
    assert "Pass: 1" in text
    assert "Fail: 1" in text
    assert "Queued: 1" in text


# ---------------------------------------------------------------------------
# TableTab tests
# ---------------------------------------------------------------------------


def test_table_tab_empty(app):
    """TableTab should have zero rows for empty data."""
    table = TableTab()
    tick = _make_tick_data_empty()
    table.update_tick(tick)

    assert table.table_widget.rowCount() == 0


def test_table_tab_with_data(app):
    """TableTab should show one row per test with correct state text."""
    table = TableTab()
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


def test_table_tab_updates_on_second_tick(app):
    """TableTab should reflect new state when update_tick is called again."""
    table = TableTab()
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
    """CoverageTab should store coverage history data for rendering."""
    from pytest_fly.gui.coverage_tab import CoverageTab

    tab = CoverageTab()
    tick = _make_tick_data_with_tests()
    now = time.time()
    tick.coverage_history = [(now - 5, 0.25), (now - 2, 0.55), (now, 0.78)]
    tab.update_tick(tick)

    assert tab.chart._coverage_history == tick.coverage_history
    assert len(tab.chart._coverage_history) == 3


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
    table = TableTab()
    table.update_tick(tick)
    assert table.table_widget.rowCount() == 1
    assert table.table_widget.item(0, 0).text() == "tests/test_no_operation.py"
    assert table.table_widget.item(0, 1).text() == PytestRunnerState.PASS.value

    # GraphTab
    graph = GraphTab()
    graph.update_tick(tick)
    assert len(graph.progress_bars) == 1
    assert "tests/test_no_operation.py" in graph.progress_bars
