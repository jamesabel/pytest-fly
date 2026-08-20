"""History tab — recent-run summaries rendered from the DB.

Covers the run rows (times, pass/fail statistics, status), the failed-test child rows,
the configurable run limit, the change-token gating that skips rebuilds when the DB
has not changed, and multi-select copy-to-clipboard.
"""

import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

from pytest_fly.db import PytestProcessInfoDB, PytestProcessInfoReader
from pytest_fly.gui.history_tab import HistoryTab
from pytest_fly.interfaces import PyTestFlyExitCode, PytestProcessInfo
from pytest_fly.preferences import get_pref, history_run_limit_default

from .paths import get_temp_dir


@pytest.fixture
def history_run_limit_pref():
    """Restore the History run-limit preference after the test."""
    yield get_pref()
    get_pref().history_run_limit = history_run_limit_default


def _record(run_guid: str, name: str, exit_code: PyTestFlyExitCode, time_stamp: float, pid: int | None = 1234) -> PytestProcessInfo:
    return PytestProcessInfo(run_guid=run_guid, name=name, pid=pid, exit_code=exit_code, output=None, time_stamp=time_stamp, put_version="put 1.0")


def _update_from_db(tab: HistoryTab, data_dir) -> None:
    with PytestProcessInfoReader(data_dir) as reader:
        tab.update_tick(reader)


def test_history_tab_rows_and_failed_children(qtbot, history_run_limit_pref):
    data_dir = get_temp_dir("history_tab_rows")
    now = time.time()
    with PytestProcessInfoDB(data_dir) as db:
        db.write(_record("run-1", "tests/test_a.py", PyTestFlyExitCode.OK, now - 100))
        db.write(_record("run-2", "tests/test_a.py", PyTestFlyExitCode.OK, now - 50))
        db.write(_record("run-2", "tests/test_b.py", PyTestFlyExitCode.TESTS_FAILED, now - 40))

    tab = HistoryTab()
    qtbot.addWidget(tab)
    _update_from_db(tab, data_dir)

    tree = tab._tree
    assert tree.topLevelItemCount() == 2
    newest = tree.topLevelItem(0)  # most recent run first
    assert newest.text(3) == "1"  # pass count
    assert newest.text(4) == "1"  # fail count
    assert newest.text(6) == "2"  # total
    assert newest.text(2) == "Complete"
    assert newest.text(7) == "put 1.0"
    assert newest.childCount() == 1
    assert newest.child(0).text(0) == "tests/test_b.py"
    assert newest.isExpanded()  # runs with failures start expanded

    oldest = tree.topLevelItem(1)
    assert oldest.text(3) == "1"
    assert oldest.text(4) == "0"
    assert oldest.childCount() == 0


def test_history_tab_in_progress_status(qtbot, history_run_limit_pref):
    data_dir = get_temp_dir("history_tab_in_progress")
    now = time.time()
    with PytestProcessInfoDB(data_dir) as db:
        db.write(_record("run-1", "tests/test_a.py", PyTestFlyExitCode.OK, now - 10))
        db.write(_record("run-1", "tests/test_b.py", PyTestFlyExitCode.NONE, now))  # still running

    tab = HistoryTab()
    qtbot.addWidget(tab)
    _update_from_db(tab, data_dir)
    assert tab._tree.topLevelItem(0).text(2) == "In progress"


def test_history_tab_run_limit(qtbot, history_run_limit_pref):
    """Only the configured number of most recent runs is shown; a limit change applies on the next tick."""
    data_dir = get_temp_dir("history_tab_run_limit")
    now = time.time()
    with PytestProcessInfoDB(data_dir) as db:
        for run_index in range(4):
            db.write(_record(f"run-{run_index}", "tests/test_a.py", PyTestFlyExitCode.OK, now - 100 + run_index))

    get_pref().history_run_limit = 2
    tab = HistoryTab()
    qtbot.addWidget(tab)
    _update_from_db(tab, data_dir)
    tree = tab._tree
    assert tree.topLevelItemCount() == 2
    assert tree.topLevelItem(0).data(0, Qt.ItemDataRole.UserRole) == "run-3"
    assert tree.topLevelItem(1).data(0, Qt.ItemDataRole.UserRole) == "run-2"

    get_pref().history_run_limit = 3  # widen mid-session; applied on the next tick
    _update_from_db(tab, data_dir)
    assert tree.topLevelItemCount() == 3


def test_history_tab_skips_rebuild_when_unchanged(qtbot, history_run_limit_pref):
    """An unchanged DB leaves the tree untouched; a new write triggers a rebuild."""
    data_dir = get_temp_dir("history_tab_unchanged")
    now = time.time()
    with PytestProcessInfoDB(data_dir) as db:
        db.write(_record("run-1", "tests/test_a.py", PyTestFlyExitCode.OK, now - 10))

    tab = HistoryTab()
    qtbot.addWidget(tab)
    _update_from_db(tab, data_dir)
    item_before = tab._tree.topLevelItem(0)
    _update_from_db(tab, data_dir)
    assert tab._tree.topLevelItem(0) is item_before  # no rebuild — same item object survives

    with PytestProcessInfoDB(data_dir) as db:
        db.write(_record("run-2", "tests/test_b.py", PyTestFlyExitCode.OK, now))
    _update_from_db(tab, data_dir)
    assert tab._tree.topLevelItemCount() == 2


def test_history_tab_collapse_survives_rebuild(qtbot, history_run_limit_pref):
    """A run the user collapsed stays collapsed when new records force a rebuild."""
    data_dir = get_temp_dir("history_tab_collapse")
    now = time.time()
    with PytestProcessInfoDB(data_dir) as db:
        db.write(_record("run-1", "tests/test_a.py", PyTestFlyExitCode.TESTS_FAILED, now - 10))

    tab = HistoryTab()
    qtbot.addWidget(tab)
    _update_from_db(tab, data_dir)
    assert tab._tree.topLevelItem(0).isExpanded()
    tab._tree.topLevelItem(0).setExpanded(False)

    with PytestProcessInfoDB(data_dir) as db:
        db.write(_record("run-1", "tests/test_b.py", PyTestFlyExitCode.OK, now))
    _update_from_db(tab, data_dir)
    assert tab._tree.topLevelItem(0).isExpanded() is False


def test_history_tab_auto_expands_when_first_failure_appears(qtbot, history_run_limit_pref):
    """A run first shown without failures still auto-expands once its first failure lands."""
    data_dir = get_temp_dir("history_tab_late_failure")
    now = time.time()
    with PytestProcessInfoDB(data_dir) as db:
        db.write(_record("run-1", "tests/test_a.py", PyTestFlyExitCode.OK, now - 10))

    tab = HistoryTab()
    qtbot.addWidget(tab)
    _update_from_db(tab, data_dir)
    assert tab._tree.topLevelItem(0).isExpanded() is False  # nothing to expand yet

    with PytestProcessInfoDB(data_dir) as db:
        db.write(_record("run-1", "tests/test_b.py", PyTestFlyExitCode.TESTS_FAILED, now))
    _update_from_db(tab, data_dir)
    assert tab._tree.topLevelItem(0).isExpanded() is True


def test_history_tab_empty_db(qtbot, history_run_limit_pref):
    data_dir = get_temp_dir("history_tab_empty")
    tab = HistoryTab()
    qtbot.addWidget(tab)
    _update_from_db(tab, data_dir)
    assert tab._tree.topLevelItemCount() == 0


def test_history_tab_copy_selection(qtbot, history_run_limit_pref):
    """Selected run rows copy as tab-separated columns and failed-test rows as names, in visual order."""
    data_dir = get_temp_dir("history_tab_copy")
    now = time.time()
    with PytestProcessInfoDB(data_dir) as db:
        db.write(_record("run-1", "tests/test_a.py", PyTestFlyExitCode.OK, now - 100))
        db.write(_record("run-2", "tests/test_a.py", PyTestFlyExitCode.OK, now - 50))
        db.write(_record("run-2", "tests/test_b.py", PyTestFlyExitCode.TESTS_FAILED, now - 40))

    tab = HistoryTab()
    qtbot.addWidget(tab)
    _update_from_db(tab, data_dir)
    tree = tab._tree

    # Select (in reverse click order, to prove visual ordering wins): the older run row,
    # then the newest run's failed-test child, then the newest run row.
    tree.topLevelItem(1).setSelected(True)
    tree.topLevelItem(0).child(0).setSelected(True)
    tree.topLevelItem(0).setSelected(True)

    tab.copy_selection_to_clipboard()
    lines = QGuiApplication.clipboard().text().splitlines()
    assert len(lines) == 3
    newest_run_line, failed_test_line, oldest_run_line = lines
    newest_columns = newest_run_line.split("\t")
    assert newest_columns[2:8] == ["Complete", "1", "1", "0", "2", "put 1.0"]  # Status through Version
    assert failed_test_line == "tests/test_b.py"
    assert oldest_run_line.split("\t")[3] == "1"  # older run's pass count


def test_history_tab_copy_empty_selection_is_noop(qtbot, history_run_limit_pref):
    """Copy with nothing selected leaves the clipboard untouched."""
    data_dir = get_temp_dir("history_tab_copy_empty")
    now = time.time()
    with PytestProcessInfoDB(data_dir) as db:
        db.write(_record("run-1", "tests/test_a.py", PyTestFlyExitCode.OK, now))

    tab = HistoryTab()
    qtbot.addWidget(tab)
    _update_from_db(tab, data_dir)

    QGuiApplication.clipboard().setText("sentinel")
    assert tab.selection_as_text() == ""
    tab.copy_selection_to_clipboard()
    assert QGuiApplication.clipboard().text() == "sentinel"


def test_history_tab_selection_survives_rebuild(qtbot, history_run_limit_pref):
    """Run-row and failed-test selections persist when new records force a rebuild."""
    data_dir = get_temp_dir("history_tab_selection_rebuild")
    now = time.time()
    with PytestProcessInfoDB(data_dir) as db:
        db.write(_record("run-1", "tests/test_a.py", PyTestFlyExitCode.TESTS_FAILED, now - 100))
        db.write(_record("run-2", "tests/test_a.py", PyTestFlyExitCode.OK, now - 50))

    tab = HistoryTab()
    qtbot.addWidget(tab)
    _update_from_db(tab, data_dir)
    tree = tab._tree
    tree.topLevelItem(0).setSelected(True)  # run-2's row
    tree.topLevelItem(1).child(0).setSelected(True)  # run-1's failed test

    with PytestProcessInfoDB(data_dir) as db:
        db.write(_record("run-2", "tests/test_b.py", PyTestFlyExitCode.OK, now))
    _update_from_db(tab, data_dir)

    assert tree.topLevelItem(0).isSelected() is True
    assert tree.topLevelItem(1).isSelected() is False
    assert tree.topLevelItem(1).child(0).isSelected() is True
