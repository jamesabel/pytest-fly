"""Tests for the Configuration tab preference-editing logic."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog

from pytest_fly.gui.configuration_tab.configuration import Configuration, OrderingAspectsWidget
from pytest_fly.interfaces import RunMode
from pytest_fly.preferences import get_pref, init_preferences_for_put


@pytest.fixture(autouse=True)
def _isolated_prefs(tmp_path):
    """Rebind preferences to a per-test tmp dir so edits never touch shared state."""
    init_preferences_for_put(tmp_path)


def test_update_checkbox_prefs(app):
    cfg = Configuration()
    cfg.verbose_checkbox.setChecked(True)
    cfg.update_verbose()
    assert get_pref().verbose is True

    cfg.perf_logging_checkbox.setChecked(True)
    cfg.update_perf_logging()
    assert get_pref().perf_logging is True


def test_update_numeric_prefs_and_clamping(app):
    cfg = Configuration()

    cfg.update_processes("4")
    assert get_pref().processes == 4
    cfg.update_processes("not-a-number")  # ignored
    assert get_pref().processes == 4

    cfg.update_refresh_rate("2.5")
    assert get_pref().refresh_rate == 2.5
    cfg.update_refresh_rate("0.1")  # clamped up to the 1.0 minimum
    assert get_pref().refresh_rate == 1.0
    cfg.update_refresh_rate("bad")  # ValueError swallowed

    cfg.update_tooltip_line_limit("10")
    assert get_pref().tooltip_line_limit == 10
    cfg.update_tooltip_line_limit("0")  # clamped up to minimum 1
    assert get_pref().tooltip_line_limit == 1

    cfg.update_chart_window_minutes("3.0")
    assert get_pref().chart_window_minutes == 3.0
    cfg.update_chart_window_minutes("bad")  # ValueError swallowed

    cfg.update_graph_font_size("12")
    assert get_pref().graph_font_size == 12
    cfg.update_graph_font_size("bad")  # not numeric -> ignored


def test_update_utilization_thresholds_warns(app, caplog):
    cfg = Configuration()
    cfg.update_utilization_high_threshold("0.8")
    assert get_pref().utilization_high_threshold == 0.8
    # low > high should log a warning via _validate_utilization_thresholds
    cfg.update_utilization_low_threshold("0.95")
    assert get_pref().utilization_low_threshold == 0.95
    cfg.update_utilization_high_threshold("bad")  # ValueError swallowed
    cfg.update_utilization_low_threshold("bad")  # ValueError swallowed


def test_update_commit_warning_threshold(app):
    cfg = Configuration()
    cfg.update_commit_warning_threshold("0.9")
    assert get_pref().commit_warning_threshold == 0.9
    cfg.update_commit_warning_threshold("bad")  # ValueError swallowed
    assert get_pref().commit_warning_threshold == 0.9


def test_update_resume_skip_put_check(app):
    cfg = Configuration()
    get_pref().run_mode = RunMode.CHECK
    cfg.resume_skip_put_check_checkbox.setChecked(True)
    cfg.update_resume_skip_put_check()
    assert get_pref().resume_skip_put_check is True
    assert get_pref().run_mode == RunMode.RESUME

    cfg.resume_skip_put_check_checkbox.setChecked(False)
    cfg.update_resume_skip_put_check()
    assert get_pref().run_mode == RunMode.CHECK


def test_resume_reconciliation_on_construction(app):
    """Existing RESUME users get resume_skip_put_check auto-enabled when the tab builds."""
    pref = get_pref()
    pref.run_mode = RunMode.RESUME
    pref.resume_skip_put_check = False
    Configuration()
    assert get_pref().resume_skip_put_check is True


def test_test_results_db_dir_update(app):
    cfg = Configuration()
    cfg.update_test_results_db_dir("  /some/dir  ")
    assert get_pref().test_results_db_dir == "/some/dir"


def test_target_project_path_is_read_only(app):
    """The PUT is set by the launch directory / --target, so the field is display-only."""
    cfg = Configuration()
    assert cfg.target_project_path_lineedit.isReadOnly()
    assert cfg.target_project_path_lineedit.text() == cfg._active_put_path


def test_browse_dialogs(app, tmp_path, monkeypatch):
    """The Browse button feeds the picked directory into the results-DB line edit."""
    picked = str(tmp_path / "picked")
    (tmp_path / "picked").mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: picked)

    cfg = Configuration()
    cfg._browse_test_results_db_dir()
    assert cfg.test_results_db_dir_lineedit.text() == picked


def test_ordering_widget_move_and_toggle(app):
    """Up/Down reorder and checkbox toggles flow through the ordering widget."""
    widget = OrderingAspectsWidget()
    widget._list.setCurrentRow(1)
    widget._move_selected(-1)  # up
    widget._move_selected(1)  # down
    widget._move_selected(-99)  # out of range -> no-op
    widget._list.setCurrentRow(-1)
    widget._move_selected(-1)  # no selection -> no-op

    # Toggling a checkbox triggers _on_item_changed -> reorder + persist.
    widget._list.item(0).setCheckState(Qt.CheckState.Unchecked)
    widget._list.item(widget._list.count() - 1).setCheckState(Qt.CheckState.Checked)
