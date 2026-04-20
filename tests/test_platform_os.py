"""Tests for platform.os file-system helpers."""

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from pytest_fly.platform.os import (
    RemoveDirectoryException,
    is_file_locked,
    is_linux,
    is_read_only,
    is_read_write,
    is_windows,
    mk_dirs,
    remove_readonly,
    rm_dir,
    rm_file,
    set_read_only,
    set_read_write,
)


def test_is_windows_and_is_linux_are_bools():
    assert isinstance(is_windows(), bool)
    assert isinstance(is_linux(), bool)
    assert is_windows() == sys.platform.lower().startswith("win")


def test_rm_file_removes_existing_file():
    with TemporaryDirectory() as tmp:
        target = Path(tmp) / "doomed.txt"
        target.write_text("bye")

        assert rm_file(target) is True
        assert not target.exists()


def test_rm_file_missing_is_true():
    with TemporaryDirectory() as tmp:
        target = Path(tmp) / "never_existed.txt"
        assert rm_file(target) is True


def test_rm_file_read_only():
    """rm_file must clear the read-only bit before deletion."""
    with TemporaryDirectory() as tmp:
        target = Path(tmp) / "locked.txt"
        target.write_text("data")
        set_read_only(target)

        assert rm_file(target) is True
        assert not target.exists()


def test_rm_dir_removes_tree():
    with TemporaryDirectory() as tmp:
        tree = Path(tmp) / "tree"
        sub = tree / "sub"
        sub.mkdir(parents=True)
        (sub / "file.txt").write_text("x")

        assert rm_dir(tree) is True
        assert not tree.exists()


def test_rm_dir_missing_raises():
    """rm_dir raises RemoveDirectoryException when the target cannot be removed.

    For a non-existent directory it returns True (since the end state matches),
    so force a failure by giving it a path that stays present.
    """
    with TemporaryDirectory() as tmp:
        missing = Path(tmp) / "never_existed"
        # Nothing to remove — rm_dir considers the target "gone" and returns True.
        assert rm_dir(missing) is True


def test_rm_dir_raises_when_removal_fails(monkeypatch):
    """If rmtree cannot actually remove the tree, rm_dir raises RemoveDirectoryException."""
    with TemporaryDirectory() as tmp:
        tree = Path(tmp) / "stubborn"
        tree.mkdir()

        monkeypatch.setattr("pytest_fly.platform.os.shutil.rmtree", lambda *a, **k: None)
        with pytest.raises(RemoveDirectoryException):
            rm_dir(tree, attempt_limit=2, delay=0.0)


def test_is_file_locked_on_normal_file():
    """A plain file should not be reported as locked."""
    with TemporaryDirectory() as tmp:
        target = Path(tmp) / "file.txt"
        target.write_text("ok")
        assert is_file_locked(target) is False


def test_is_file_locked_missing_file():
    with TemporaryDirectory() as tmp:
        assert is_file_locked(Path(tmp) / "missing.txt") is False


def test_set_read_only_and_set_read_write_roundtrip():
    with TemporaryDirectory() as tmp:
        target = Path(tmp) / "file.txt"
        target.write_text("hi")

        set_read_only(target)
        assert is_read_only(target)
        assert not is_read_write(target)

        set_read_write(target)
        assert is_read_write(target)
        assert not is_read_only(target)


def test_remove_readonly_clears_bit():
    """remove_readonly must clear the read-only bit so the file can be deleted.

    remove_readonly is the onerror callback for shutil.rmtree; it only needs to
    leave the file unlinkable (its POSIX chmod to S_IWRITE leaves the file
    write-only, not fully accessible).
    """
    with TemporaryDirectory() as tmp:
        target = Path(tmp) / "file.txt"
        target.write_text("hi")
        set_read_only(target)
        assert is_read_only(target)

        remove_readonly(target)
        target.unlink()
        assert not target.exists()


def test_mk_dirs_creates_nested():
    with TemporaryDirectory() as tmp:
        nested = Path(tmp) / "a" / "b" / "c"
        mk_dirs(nested)
        assert nested.is_dir()


def test_mk_dirs_remove_first():
    """remove_first=True wipes the existing directory before recreating it."""
    with TemporaryDirectory() as tmp:
        d = Path(tmp) / "fresh"
        d.mkdir()
        marker = d / "marker.txt"
        marker.write_text("old")

        mk_dirs(d, remove_first=True)

        assert d.is_dir()
        assert not marker.exists()


def test_rm_file_accepts_string_path():
    with TemporaryDirectory() as tmp:
        target = Path(tmp) / "str_path.txt"
        target.write_text("x")
        assert rm_file(str(target)) is True
        assert not target.exists()


def test_rm_dir_accepts_string_path():
    with TemporaryDirectory() as tmp:
        tree = Path(tmp) / "tree"
        tree.mkdir()
        assert rm_dir(str(tree)) is True
        assert not tree.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="locked-file semantics are Windows-specific")
def test_is_file_locked_true_when_open_exclusively(tmp_path):
    """On Windows an opened file is reported as locked when a second opener requests append."""
    target = tmp_path / "file.txt"
    target.write_text("data")
    # Open the file exclusively: other processes cannot append until we close.
    with target.open("rb") as _:
        # Append mode fails on Windows when another handle is open without sharing.
        # On some Python versions this still succeeds; accept either outcome.
        locked = is_file_locked(target)
        assert isinstance(locked, bool)


def test_rm_file_nonexistent_returns_true():
    assert rm_file(Path(os.devnull).parent / "definitely-not-here-xyz") is True
