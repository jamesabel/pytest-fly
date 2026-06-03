"""Tests for the application bootstrap in :mod:`pytest_fly.main`."""

from pathlib import Path

from pytest_fly import main as main_module
from pytest_fly.main import _parse_args, app_main


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


def test_app_main_resolves_target_and_launches(tmp_path, monkeypatch):
    """app_main wires the resolved PUT/data dirs into fly_main and creates the data dir."""
    captured = {}

    def fake_fly_main(data_dir, *, auto_start=False, auto_quit_on_done=False):
        captured["data_dir"] = data_dir
        captured["auto_start"] = auto_start
        captured["auto_quit_on_done"] = auto_quit_on_done

    # Stub out the blocking GUI launch and the global-logging reconfig.
    monkeypatch.setattr(main_module, "fly_main", fake_fly_main)
    monkeypatch.setattr(main_module, "init_parent_logger", lambda verbose: None)

    target = tmp_path / "put"
    target.mkdir()
    data_dir = tmp_path / "results"

    app_main(["--target", str(target), "--data-dir", str(data_dir), "--auto-start"])

    assert captured["data_dir"] == data_dir.resolve()
    assert captured["auto_start"] is True
    assert captured["auto_quit_on_done"] is False
    assert data_dir.exists()  # app_main creates the data dir


def test_app_main_uses_cwd_when_no_target_arg(tmp_path, monkeypatch):
    """With no --target, app_main resolves the PUT to the current working directory."""
    captured = {}

    monkeypatch.setattr(main_module, "fly_main", lambda data_dir, **kw: captured.setdefault("data_dir", data_dir))
    monkeypatch.setattr(main_module, "init_parent_logger", lambda verbose: None)
    monkeypatch.setattr(main_module, "init_preferences_for_put", lambda put_path: captured.setdefault("put_path", put_path))

    cwd = tmp_path / "cwd_put"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    data_dir = tmp_path / "results2"
    app_main(["--data-dir", str(data_dir)])

    # The PUT is the cwd; nothing global was consulted.
    assert captured["put_path"].resolve() == cwd.resolve()
    assert captured["data_dir"] == data_dir.resolve()
