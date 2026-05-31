"""Tests for last-target persistence in :mod:`pytest_fly.paths`."""

import pytest_fly.paths as paths_module
from pytest_fly.paths import _last_target_file, read_last_target, write_last_target


def test_last_target_file_name():
    """The real config path ends with the expected file name."""
    assert _last_target_file().name == "last_target.txt"


def test_read_last_target_missing(tmp_path, monkeypatch):
    """No file on disk -> None."""
    monkeypatch.setattr(paths_module, "_last_target_file", lambda: tmp_path / "last_target.txt")
    assert read_last_target() is None


def test_read_last_target_empty_file(tmp_path, monkeypatch):
    """A whitespace-only file -> None."""
    target_file = tmp_path / "last_target.txt"
    target_file.write_text("   \n", encoding="utf-8")
    monkeypatch.setattr(paths_module, "_last_target_file", lambda: target_file)
    assert read_last_target() is None


def test_write_then_read_last_target(tmp_path, monkeypatch):
    """write_last_target persists a resolved path that read_last_target returns."""
    target_file = tmp_path / "cfg" / "last_target.txt"  # parent dir does not exist yet
    monkeypatch.setattr(paths_module, "_last_target_file", lambda: target_file)

    put = tmp_path / "my_put"
    put.mkdir()
    write_last_target(put)

    assert target_file.is_file()
    assert read_last_target() == put.resolve()
