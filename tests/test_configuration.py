"""Tests for the Configuration tab preference-editing logic."""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog

from pytest_fly.gui.configuration_tab import configuration as configuration_module
from pytest_fly.gui.configuration_tab.configuration import Configuration, OrderingAspectsWidget
from pytest_fly.interfaces import OrderingAspect, RunMode
from pytest_fly.paths import get_workspace_dir, init_workspace
from pytest_fly.preferences import (
    cpu_gate_threshold_default,
    get_active_put_path,
    get_ordering_aspects_ordered,
    get_pref,
    refresh_rate_default,
    set_ordering_aspects_ordered,
    stall_warn_unit_default,
    stall_warn_value_default,
    tooltip_line_limit_default,
)


@pytest.fixture(autouse=True)
def _isolated_workspace(tmp_path):
    """Rebind the workspace to a per-test tmp dir so edits never touch shared state."""
    init_workspace(tmp_path)


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


def test_apply_defaults_resets_prefs_and_widgets(app):
    """_apply_defaults returns every tab-visible preference (and its widget) to the default."""
    cfg = Configuration()

    # Change a spread of settings through their normal slots (widgets deliberately left stale
    # for some — the reset must fix prefs even when the widget text already shows the default).
    cfg.update_refresh_rate("9.5")
    cfg.update_cpu_gate_threshold("0.5")
    cfg.cpu_gate_enabled_checkbox.setChecked(True)
    cfg.update_tooltip_line_limit(str(tooltip_line_limit_default))  # pref == default, widget in sync
    cfg.update_stall_warn()  # no-op parse; then set directly:
    get_pref().stall_warn_value = 99.0
    get_pref().stall_warn_unit = "Hours"
    cfg.update_test_results_db_dir("/some/dir")
    get_pref().put_path = "/stale/put"
    set_ordering_aspects_ordered([OrderingAspect.COVERAGE_EFFICIENCY])

    cfg._apply_defaults()

    pref = get_pref()
    assert pref.refresh_rate == refresh_rate_default
    assert pref.cpu_gate_threshold == cpu_gate_threshold_default
    assert pref.cpu_gate_enabled is False
    assert pref.tooltip_line_limit == tooltip_line_limit_default
    assert pref.stall_warn_value == stall_warn_value_default
    assert pref.stall_warn_unit == stall_warn_unit_default
    assert pref.test_results_db_dir == ""
    assert pref.put_path == ""
    assert get_ordering_aspects_ordered() == [OrderingAspect.FAILED_FIRST, OrderingAspect.NEVER_RUN_FIRST]

    # Widgets reflect the defaults.
    assert float(cfg.refresh_rate_lineedit.text()) == refresh_rate_default
    assert float(cfg.cpu_gate_threshold_lineedit.text()) == cpu_gate_threshold_default
    assert cfg.cpu_gate_enabled_checkbox.isChecked() is False
    assert cfg.stall_warn_unit_combo.currentText() == stall_warn_unit_default
    assert cfg.test_results_db_dir_lineedit.text() == ""
    assert cfg.target_project_path_lineedit.text() == str(get_workspace_dir())
    assert not cfg.utilization_warning_label.isVisibleTo(cfg)
    assert not cfg.stall_kill_warning_label.isVisibleTo(cfg)


def test_restore_defaults_asks_for_confirmation(app, monkeypatch):
    """The button-facing entry point resets only when the user confirms."""
    from PySide6.QtWidgets import QMessageBox

    cfg = Configuration()
    cfg.update_refresh_rate("9.5")

    monkeypatch.setattr(configuration_module.QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)
    cfg.restore_defaults()
    assert get_pref().refresh_rate == 9.5  # declined — nothing changes

    monkeypatch.setattr(configuration_module.QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    cfg.restore_defaults()
    assert get_pref().refresh_rate == refresh_rate_default


def test_update_cpu_gate_prefs(app):
    cfg = Configuration()

    cfg.cpu_gate_enabled_checkbox.setChecked(True)
    cfg.update_cpu_gate_enabled()
    assert get_pref().cpu_gate_enabled is True

    cfg.update_cpu_gate_threshold("0.75")
    assert get_pref().cpu_gate_threshold == 0.75
    cfg.update_cpu_gate_threshold("bad")  # ValueError swallowed
    assert get_pref().cpu_gate_threshold == 0.75


def test_update_resource_guard_prefs(app):
    cfg = Configuration()

    cfg.resource_guard_enabled_checkbox.setChecked(True)
    cfg.update_resource_guard_enabled()
    assert get_pref().resource_guard_enabled is True

    cfg.update_resource_guard_min_free_disk_gb("25")
    assert get_pref().resource_guard_min_free_disk_gb == 25.0
    cfg.update_resource_guard_min_free_disk_gb("-5")  # clamped up to 0 (0 disables the disk check)
    assert get_pref().resource_guard_min_free_disk_gb == 0.0
    cfg.update_resource_guard_min_free_disk_gb("bad")  # ValueError swallowed
    assert get_pref().resource_guard_min_free_disk_gb == 0.0

    cfg.update_resource_guard_commit_threshold("0.9")
    assert get_pref().resource_guard_commit_threshold == 0.9
    cfg.update_resource_guard_commit_threshold("bad")  # ValueError swallowed
    assert get_pref().resource_guard_commit_threshold == 0.9


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


def test_target_project_path_defaults_to_workspace(app):
    """With no stored PUT, the field shows the workspace dir (empty pref resolves to it)."""
    cfg = Configuration()
    assert get_pref().put_path == ""
    assert cfg.target_project_path_lineedit.text() == str(get_workspace_dir())


def test_commit_target_project_path_persists(app, tmp_path):
    """Editing the field persists the PUT preference, applied on the next run."""
    new_dir = tmp_path / "new_target"
    new_dir.mkdir()

    cfg = Configuration()
    cfg.target_project_path_lineedit.setText(str(new_dir))
    cfg._commit_target_project_path()

    assert get_pref().put_path == str(new_dir.resolve())
    assert get_active_put_path() == new_dir.resolve()


def test_commit_empty_target_falls_back_to_workspace(app, tmp_path):
    """Clearing the field clears the stored PUT and restores the workspace dir."""
    cfg = Configuration()
    get_pref().put_path = str(tmp_path / "stale")

    cfg.target_project_path_lineedit.setText("   ")
    cfg._commit_target_project_path()

    assert get_pref().put_path == ""
    assert cfg.target_project_path_lineedit.text() == str(get_workspace_dir())


def test_browse_dialogs(app, tmp_path, monkeypatch):
    """The Browse buttons feed the picked directory into their line edits."""
    picked = str(tmp_path / "picked")
    (tmp_path / "picked").mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: picked)

    cfg = Configuration()
    cfg._browse_test_results_db_dir()
    assert cfg.test_results_db_dir_lineedit.text() == picked

    cfg._browse_target_project_path()
    assert cfg.target_project_path_lineedit.text() == picked
    assert get_pref().put_path == str(Path(picked).resolve())


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
