"""Tests for the application bootstrap in :mod:`pytest_fly.main`."""

import os
from pathlib import Path

import pytest

import pytest_fly.paths as paths_module
from pytest_fly import main as main_module
from pytest_fly.const import PYTEST_FLY_WORKSPACE_STRING
from pytest_fly.main import _parse_args, app_main
from pytest_fly.preferences import reset_pref_cache


@pytest.fixture(autouse=True)
def _restore_workspace_binding():
    """app_main rebinds the workspace to cwd; restore the session binding afterward.

    Without this, these tests would leave paths._workspace_dir pointing at a deleted tmp dir
    and break later tests that rely on the session-scoped workspace.
    """
    saved_dir = paths_module._workspace_dir
    saved_env = os.environ.get(PYTEST_FLY_WORKSPACE_STRING)
    yield
    paths_module._workspace_dir = saved_dir
    if saved_env is None:
        os.environ.pop(PYTEST_FLY_WORKSPACE_STRING, None)
    else:
        os.environ[PYTEST_FLY_WORKSPACE_STRING] = saved_env
    reset_pref_cache()


def test_parse_args_defaults():
    """No CLI args -> all options fall back to their defaults."""
    args = _parse_args([])
    assert args.target is None
    assert args.data_dir is None
    assert args.auto_start is False
    assert args.auto_quit_on_done is False


def test_parse_args_all_options():
    """Every option is parsed into the namespace."""
    args = _parse_args(["--target", "proj", "--data-dir", "results", "--auto-start", "--auto-quit-on-done"])
    assert Path(args.target) == Path("proj")
    assert Path(args.data_dir) == Path("results")
    assert args.auto_start is True
    assert args.auto_quit_on_done is True


def test_app_main_persists_target_and_launches(tmp_path, monkeypatch):
    """--target persists as the configured PUT; the workspace roots at the launch dir."""
    captured = {}

    def fake_fly_main(data_dir, *, auto_start=False, auto_quit_on_done=False):
        captured["data_dir"] = data_dir
        captured["auto_start"] = auto_start
        captured["auto_quit_on_done"] = auto_quit_on_done

    # Stub out the blocking GUI launch and the global-logging reconfig.
    monkeypatch.setattr(main_module, "fly_main", fake_fly_main)
    monkeypatch.setattr(main_module, "init_parent_logger", lambda verbose: None)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    target = tmp_path / "put"
    target.mkdir()
    data_dir = tmp_path / "results"

    app_main(["--target", str(target), "--data-dir", str(data_dir), "--auto-start"])

    assert main_module.get_workspace_dir() == workspace.resolve()  # storage rooted at the launch dir
    assert main_module.get_active_put_path() == target.resolve()  # --target persisted as the PUT
    assert captured["data_dir"] == data_dir.resolve()
    assert captured["auto_start"] is True
    assert captured["auto_quit_on_done"] is False
    assert data_dir.exists()  # app_main creates the data dir


def test_app_main_put_defaults_to_workspace_when_no_target(tmp_path, monkeypatch):
    """With no --target and no stored PUT, the PUT resolves to the workspace (launch) dir."""
    captured = {}

    monkeypatch.setattr(main_module, "fly_main", lambda data_dir, **kw: captured.setdefault("data_dir", data_dir))
    monkeypatch.setattr(main_module, "init_parent_logger", lambda verbose: None)

    workspace = tmp_path / "workspace2"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    data_dir = tmp_path / "results2"
    app_main(["--data-dir", str(data_dir)])

    assert main_module.get_active_put_path() == workspace.resolve()
    assert captured["data_dir"] == data_dir.resolve()
