"""Tests for the per-test TableTab grid logic."""

import time

from PySide6.QtGui import QColor

from pytest_fly.gui.gui_main import build_tick_data
from pytest_fly.gui.table_tab.table_tab import Columns, TableTab, _SortableItem, format_commit, set_utilization_color
from pytest_fly.interfaces import PyTestFlyExitCode, PytestProcessInfo
from pytest_fly.pytest_runner.live_output import live_output_path

from .paths import get_temp_dir


def _info(name, pid, exit_code, ts, cpu=None, mem=None, output=None, commit=None):
    return PytestProcessInfo(run_guid="g", name=name, pid=pid, exit_code=exit_code, output=output, time_stamp=ts, cpu_percent=cpu, memory_percent=mem, commit_bytes=commit)


def _completed_tick():
    now = time.time()
    infos = [
        _info("tests/test_a.py", None, PyTestFlyExitCode.NONE, now - 10),
        _info("tests/test_a.py", 1, PyTestFlyExitCode.NONE, now - 9),
        _info("tests/test_a.py", 1, PyTestFlyExitCode.OK, now - 5, cpu=150.0, mem=2.5, output="1 passed"),
        _info("tests/test_b.py", None, PyTestFlyExitCode.NONE, now - 10),
        _info("tests/test_b.py", 2, PyTestFlyExitCode.TESTS_FAILED, now - 4, cpu=80.0, mem=1.0, output="1 failed"),
    ]
    return build_tick_data(infos)


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


def test_set_utilization_color_thresholds(app):
    """Cell color is red above high, yellow above low, default otherwise."""
    from PySide6.QtWidgets import QTableWidgetItem

    item = QTableWidgetItem()
    set_utilization_color(item, 0.95, 0.8, 0.5)
    assert item.foreground().color() == QColor("red")
    set_utilization_color(item, 0.6, 0.8, 0.5)
    assert item.foreground().color() == QColor("yellow")
    set_utilization_color(item, 0.1, 0.8, 0.5)  # default brush, no crash
    assert item.foreground().color() != QColor("red")


def test_format_commit():
    """Commit charge formats as GB at/above 1 GiB, MB below, and '' when unknown."""
    assert format_commit(None) == ""
    assert format_commit(0) == "0 MB"
    assert format_commit(134 * 1024 * 1024) == "134 MB"
    assert format_commit(2 * 1024 * 1024 * 1024) == "2.00 GB"


def test_table_tab_commit_column(app):
    """The Commit column shows the final record's peak commit charge."""
    now = time.time()
    infos = [
        _info("tests/test_c.py", None, PyTestFlyExitCode.NONE, now - 5),
        _info("tests/test_c.py", 1, PyTestFlyExitCode.OK, now - 1, cpu=50.0, mem=1.0, output="ok", commit=2 * 1024 * 1024 * 1024),
    ]
    table = TableTab(get_temp_dir("table_commit"))
    table.update_tick(build_tick_data(infos))
    assert table.table_widget.item(0, Columns.COMMIT.value).text() == "2.00 GB"


def test_sortable_item_numeric_and_text(app):
    """_SortableItem compares by numeric key when both present, else by text."""
    from pytest_fly.gui.table_tab.table_tab import _SORT_KEY_ROLE

    a = _SortableItem()
    b = _SortableItem()
    a.setData(_SORT_KEY_ROLE, 1.0)
    b.setData(_SORT_KEY_ROLE, 2.0)
    assert a < b  # numeric

    c = _SortableItem()
    c.setText("alpha")
    d = _SortableItem()
    d.setText("beta")
    assert c < d  # text fallback (no numeric keys)

    assert c.__lt__("not an item") is NotImplemented


# ---------------------------------------------------------------------------
# update_tick / row lifecycle
# ---------------------------------------------------------------------------


def test_table_tab_populates_rows(app):
    """update_tick fills a row per test with state and resource columns."""
    table = TableTab(get_temp_dir("table_populate"))
    table.update_tick(_completed_tick())
    assert table.table_widget.rowCount() == 2
    states = {table.table_widget.item(r, Columns.STATE.value).text() for r in range(2)}
    assert "Pass" in states
    assert "Fail" in states


def test_table_tab_running_reads_live_output(app):
    """A running test pulls its tooltip from the live-output file on disk."""
    data_dir = get_temp_dir("table_live")
    name = "tests/test_run.py"
    path = live_output_path(data_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("live tail line\n")

    now = time.time()
    infos = [_info(name, None, PyTestFlyExitCode.NONE, now - 2), _info(name, 1, PyTestFlyExitCode.NONE, now - 1)]
    table = TableTab(data_dir)
    table.update_tick(build_tick_data(infos))
    state_item = table.table_widget.item(0, Columns.STATE.value)
    assert "live tail line" in state_item.toolTip()


def test_table_tab_singleton_name(app):
    """A singleton test gets a '(singleton)' suffix in the name column."""
    now = time.time()
    infos = [_info("tests/test_s.py", 1, PyTestFlyExitCode.OK, now, output="ok")]
    tick = build_tick_data(infos)
    tick.singleton_names = {"tests/test_s.py"}
    table = TableTab(get_temp_dir("table_singleton"))
    table.update_tick(tick)
    assert "(singleton)" in table.table_widget.item(0, Columns.NAME.value).text()


def test_table_tab_per_test_coverage_and_last_pass(app):
    """Coverage and last-pass columns are populated from tick data."""
    tick = _completed_tick()
    tick.per_test_coverage = {"tests/test_a.py": 0.42}
    tick.last_pass_data = {"tests/test_a.py": (time.time() - 100, 4.0)}
    table = TableTab(get_temp_dir("table_cov"))
    table.update_tick(tick)
    table._rebuild_row_by_name()
    row = table._row_by_name["tests/test_a.py"]
    assert "42.0%" in table.table_widget.item(row, Columns.COVERAGE.value).text()
    assert table.table_widget.item(row, Columns.LAST_PASS_DURATION.value).text() != ""


def test_table_tab_reset_clears_rows(app):
    """reset clears all rows and the name->row index."""
    table = TableTab(get_temp_dir("table_reset"))
    table.update_tick(_completed_tick())
    assert table.table_widget.rowCount() > 0
    table.reset()
    assert table.table_widget.rowCount() == 0
    assert table._row_by_name == {}


def test_table_tab_rebuild_when_tests_shrink(app):
    """When the known test set is no longer a subset, the table rebuilds."""
    table = TableTab(get_temp_dir("table_shrink"))
    table.update_tick(_completed_tick())  # test_a, test_b
    now = time.time()
    smaller = build_tick_data([_info("tests/test_c.py", 1, PyTestFlyExitCode.OK, now, output="ok")])
    table.update_tick(smaller)  # different set -> rebuild
    names = {table.table_widget.item(r, Columns.NAME.value).data(0x0100) for r in range(table.table_widget.rowCount())}  # UserRole
    assert "tests/test_c.py" in {n for n in names if n}


def test_table_tab_sorting(app):
    """Activating a sort column sorts rows and survives subsequent ticks."""
    table = TableTab(get_temp_dir("table_sort"))
    table.update_tick(_completed_tick())
    table._on_header_double_clicked(Columns.NAME.value)  # ascending
    table._on_header_double_clicked(Columns.NAME.value)  # toggle to descending
    table.update_tick(_completed_tick())  # re-sort path
    assert table._sort_column == Columns.NAME.value


def test_table_tab_copy_selected_text(app):
    """copy_selected_text places the selected cells on the clipboard."""
    from PySide6.QtGui import QGuiApplication

    table = TableTab(get_temp_dir("table_copy"))
    table.update_tick(_completed_tick())
    table.table_widget.selectAll()
    table.copy_selected_text()
    assert QGuiApplication.clipboard().text() != ""


def _menu_exec_returning(action_text):
    """Return a QMenu.exec_ replacement that selects the action with the given text."""

    def _fake_exec(self, *args, **kwargs):
        for action in self.actions():
            if action.text() == action_text:
                return action
        return None

    return _fake_exec


def test_table_tab_context_menu_copies_output(app, monkeypatch):
    """The 'Copy Pytest Output' menu entry copies a test's full output to the clipboard."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QMenu

    table = TableTab(get_temp_dir("table_menu_copy"))
    table.update_tick(_completed_tick())
    QGuiApplication.clipboard().clear()
    table.table_widget.setCurrentCell(0, Columns.NAME.value)  # so currentItem() resolves the row

    monkeypatch.setattr(QMenu, "exec_", _menu_exec_returning("Copy Pytest Output"))
    table.show_context_menu(QPoint(0, 0))
    # test_a.py's output ("1 passed") or test_b.py's ("1 failed") lands on the clipboard
    assert QGuiApplication.clipboard().text() in {"1 passed", "1 failed"}


def test_table_tab_context_menu_force_stop_emits(app, monkeypatch):
    """The 'Force Stop' entry (shown only for running tests) emits the node_id signal."""
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QMenu

    data_dir = get_temp_dir("table_menu_stop")
    name = "tests/test_run.py"
    now = time.time()
    infos = [_info(name, None, PyTestFlyExitCode.NONE, now - 2), _info(name, 1, PyTestFlyExitCode.NONE, now - 1)]
    table = TableTab(data_dir)
    table.update_tick(build_tick_data(infos))
    table.table_widget.setCurrentCell(0, Columns.NAME.value)

    emitted = []
    table.force_stop_test_requested.connect(emitted.append)
    monkeypatch.setattr(QMenu, "exec_", _menu_exec_returning("Force Stop"))
    table.show_context_menu(QPoint(0, 0))
    assert emitted == [name]
