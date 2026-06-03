"""Tests for the missing-target-project-path guidance dialog."""

import pytest
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog

from pytest_fly.gui.target_path_dialog import TargetProjectPathDialog, ensure_valid_target_project_path
from pytest_fly.paths import init_workspace
from pytest_fly.preferences import get_pref


@pytest.fixture(autouse=True)
def _isolated_workspace(tmp_path):
    """Per-test workspace so the configured PUT (a pref) is isolated."""
    init_workspace(tmp_path)


def test_ensure_returns_existing_put_without_dialog(app, tmp_path, monkeypatch):
    """A valid configured PUT short-circuits — the dialog is never constructed."""
    target = tmp_path / "proj"
    target.mkdir()
    get_pref().put_path = str(target)

    def _boom(*a, **k):
        raise AssertionError("dialog should not be shown when the PUT is valid")

    monkeypatch.setattr("pytest_fly.gui.target_path_dialog.TargetProjectPathDialog", _boom)

    assert ensure_valid_target_project_path() == target.resolve()


def test_ensure_prompts_and_persists_when_put_missing(app, tmp_path, monkeypatch):
    """A missing PUT triggers the dialog; an accepted choice is returned and persisted."""
    get_pref().put_path = str(tmp_path / "gone")
    chosen = tmp_path / "chosen"
    chosen.mkdir()

    def fake_exec(self):
        # Simulate the user picking a valid directory and accepting.
        self.path_lineedit.setText(str(chosen))
        self._on_accept()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(TargetProjectPathDialog, "exec", fake_exec)

    result = ensure_valid_target_project_path()
    assert result == chosen.resolve()
    assert get_pref().put_path == str(chosen.resolve())


def test_ensure_returns_none_when_cancelled(app, tmp_path, monkeypatch):
    """Cancelling the dialog yields None so callers can abort."""
    get_pref().put_path = str(tmp_path / "gone")
    monkeypatch.setattr(TargetProjectPathDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    assert ensure_valid_target_project_path() is None


def test_dialog_validation_toggles_ok(app, tmp_path):
    """OK is enabled only while the entered path is an existing directory."""
    good = tmp_path / "good"
    good.mkdir()
    dialog = TargetProjectPathDialog(tmp_path / "missing")
    ok_button = dialog.button_box.button(QDialogButtonBox.StandardButton.Ok)

    assert not ok_button.isEnabled()  # prefilled missing path
    dialog.path_lineedit.setText(str(good))
    assert ok_button.isEnabled()
    dialog.path_lineedit.setText(str(tmp_path / "nope"))
    assert not ok_button.isEnabled()


def test_dialog_accept_persists_selected_path(app, tmp_path):
    """Accepting with a valid directory persists it and exposes it via selected_path()."""
    good = tmp_path / "good"
    good.mkdir()
    dialog = TargetProjectPathDialog(tmp_path / "missing")
    dialog.path_lineedit.setText(str(good))
    dialog._on_accept()

    assert dialog.selected_path() == good.resolve()
    assert get_pref().put_path == str(good.resolve())


def test_dialog_browse_sets_text(app, tmp_path, monkeypatch):
    """Browse feeds the picked directory into the line edit."""
    picked = tmp_path / "picked"
    picked.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(picked))

    dialog = TargetProjectPathDialog(tmp_path / "missing")
    dialog._browse()
    assert dialog.path_lineedit.text() == str(picked)
