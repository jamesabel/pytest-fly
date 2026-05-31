"""Additional coverage for cross-platform helpers in :mod:`pytest_fly.platform.os`.

Several helpers branch on :func:`is_windows`.  Since CI runs on Linux and the
Windows branches would otherwise never execute there (and vice versa), the
permission tests force both branches via monkeypatch so coverage is platform-independent.
"""

import pytest

import pytest_fly.platform.os as os_module
from pytest_fly.platform.os import (
    is_file_locked,
    is_read_only,
    is_read_write,
    mk_dirs,
    remove_readonly_onerror,
    rm_file,
    set_read_only,
    set_read_write,
)


@pytest.mark.parametrize("force_windows", [True, False])
def test_read_only_read_write_roundtrip(tmp_path, monkeypatch, force_windows):
    """set/is read-only and read-write round-trip under both the Windows and POSIX branches."""
    monkeypatch.setattr(os_module, "is_windows", lambda: force_windows)
    f = tmp_path / "perm.txt"
    f.write_text("data")

    set_read_only(f)
    assert is_read_only(f)

    set_read_write(f)
    assert is_read_write(f)

    # leave it writable so the tmp dir can be cleaned up
    set_read_write(f)


def test_is_file_locked_false_for_normal_file(tmp_path):
    """A normal, closed file is not reported as locked."""
    f = tmp_path / "f.txt"
    f.write_text("x")
    assert is_file_locked(f) is False


def test_is_file_locked_false_for_missing_file(tmp_path):
    """A non-existent file is not locked."""
    assert is_file_locked(tmp_path / "missing.txt") is False


def test_rm_file_removes_file(tmp_path):
    """rm_file deletes the file and returns True."""
    f = tmp_path / "x.txt"
    f.write_text("x")
    assert rm_file(f) is True
    assert not f.exists()


def test_rm_file_on_missing_is_success(tmp_path):
    """Removing an already-absent file succeeds (nothing to do)."""
    assert rm_file(tmp_path / "gone.txt") is True


def test_remove_readonly_onerror_clears_flag_and_retries(tmp_path):
    """The rmtree onerror callback strips read-only then re-invokes the failed op."""
    f = tmp_path / "ro.txt"
    f.write_text("x")
    set_read_write(f)
    retried = []
    remove_readonly_onerror(lambda p: retried.append(p), str(f), None)
    assert retried == [str(f)]


def test_mk_dirs_creates_nested(tmp_path):
    """mk_dirs creates a nested directory tree."""
    d = tmp_path / "a" / "b" / "c"
    mk_dirs(d)
    assert d.is_dir()


def test_mk_dirs_remove_first(tmp_path):
    """mk_dirs(remove_first=True) clears existing contents first."""
    d = tmp_path / "d"
    d.mkdir()
    (d / "old.txt").write_text("stale")
    mk_dirs(d, remove_first=True)
    assert d.is_dir()
    assert not (d / "old.txt").exists()
