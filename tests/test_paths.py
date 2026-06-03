"""Tests for workspace-rooted storage paths in :mod:`pytest_fly.paths`."""

from pathlib import Path

from pytest_fly.const import PYTEST_FLY_DATA_DIR_STRING, PYTEST_FLY_WORKSPACE_STRING
from pytest_fly.paths import (
    fly_dir_name,
    get_default_data_dir,
    get_fly_data_dir,
    get_log_dir,
    get_preferences_db_path,
    get_workspace_dir,
    init_workspace,
)


def test_storage_paths_root_under_workspace(tmp_path):
    """Prefs, logs, and the data dir all live under <workspace>/.pytest-fly/."""
    init_workspace(tmp_path)

    fly_dir = get_fly_data_dir()
    assert fly_dir == tmp_path.resolve() / fly_dir_name
    assert fly_dir.is_dir()
    assert get_preferences_db_path() == fly_dir / "preferences.db"
    assert get_log_dir() == fly_dir / "logs"
    assert get_log_dir().is_dir()


def test_default_data_dir_is_workspace_local(tmp_path, monkeypatch):
    """With no env override, the test-results DB dir is the workspace's .pytest-fly dir."""
    monkeypatch.delenv(PYTEST_FLY_DATA_DIR_STRING, raising=False)
    init_workspace(tmp_path)

    result = get_default_data_dir()

    assert result == tmp_path.resolve() / fly_dir_name
    assert result.is_dir()


def test_env_var_overrides_default_data_dir(tmp_path, monkeypatch):
    """PYTEST_FLY_DATA_DIR takes precedence over the workspace-local default."""
    override = tmp_path / "custom_data"
    monkeypatch.setenv(PYTEST_FLY_DATA_DIR_STRING, str(override))
    init_workspace(tmp_path)

    result = get_default_data_dir()

    assert result == override
    assert result.is_dir()


def test_workspace_falls_back_to_env_var(tmp_path, monkeypatch):
    """A child with no in-process binding resolves the workspace from PYTEST_FLY_WORKSPACE."""
    import pytest_fly.paths as paths_module

    monkeypatch.setattr(paths_module, "_workspace_dir", None)
    monkeypatch.setenv(PYTEST_FLY_WORKSPACE_STRING, str(tmp_path))

    assert get_workspace_dir() == Path(tmp_path)
