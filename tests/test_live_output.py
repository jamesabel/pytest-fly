"""Tests for :mod:`pytest_fly.pytest_runner.live_output`."""

from pathlib import Path
from tempfile import TemporaryDirectory

from pytest_fly.file_util import sanitize_test_name
from pytest_fly.pytest_runner import live_output
from pytest_fly.pytest_runner.live_output import (
    clear_live_output,
    live_output_dir,
    live_output_path,
    read_live_output,
)


def _write_log(data_dir: Path, test_name: str, data: bytes) -> Path:
    """Create the live-output file for a test and write raw bytes to it."""
    path = live_output_path(data_dir, test_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_live_output_dir():
    """Directory is the live_output subdir of the data dir."""
    data_dir = Path("some", "data")
    assert live_output_dir(data_dir) == Path("some", "data", "live_output")


def test_live_output_path_sanitizes_name():
    """File name is the sanitized test node id with a .log suffix."""
    data_dir = Path("data")
    name = "tests/test_a.py::test_b"
    path = live_output_path(data_dir, name)
    assert path == Path("data", "live_output", f"{sanitize_test_name(name)}.log")
    # The unsafe characters must not survive into the filename.
    assert "/" not in path.name and ":" not in path.name


def test_read_live_output_missing_returns_none():
    """A test with no live-output file yields None."""
    with TemporaryDirectory() as tmp:
        assert read_live_output(Path(tmp), "tests/test_missing.py") is None


def test_read_live_output_roundtrips_small_file():
    """A small file is returned verbatim."""
    live_output._read_cache.clear()
    with TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        _write_log(data_dir, "tests/test_a.py", b"hello\nworld\n")
        assert read_live_output(data_dir, "tests/test_a.py") == "hello\nworld\n"


def test_read_live_output_uses_cache_for_unchanged_file():
    """A second read of an unchanged file returns the cached value."""
    live_output._read_cache.clear()
    with TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        path = _write_log(data_dir, "tests/test_a.py", b"first\n")
        assert read_live_output(data_dir, "tests/test_a.py") == "first\n"
        # Mutate the cache entry directly: if the file is re-read, this fake value
        # is overwritten; if the cache is used, it is returned unchanged.
        size, mtime, _ = live_output._read_cache[path]
        live_output._read_cache[path] = (size, mtime, "CACHED")
        assert read_live_output(data_dir, "tests/test_a.py") == "CACHED"


def test_read_live_output_truncates_large_file():
    """A file larger than max_bytes drops the first partial line and is marked truncated."""
    live_output._read_cache.clear()
    with TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        # 5 lines of 100 'a' chars each; read only the tail so the first line is partial.
        body = b"\n".join(b"a" * 100 for _ in range(5)) + b"\n"
        _write_log(data_dir, "tests/test_big.py", body)
        result = read_live_output(data_dir, "tests/test_big.py", max_bytes=250)
        assert result is not None
        assert result.startswith("...[truncated]...\n")
        # The partial leading line was dropped, so only whole lines remain after the marker.
        assert result.count("a" * 100) < 5


def test_read_live_output_replaces_invalid_utf8():
    """Non-UTF-8 bytes decode with replacement instead of crashing."""
    live_output._read_cache.clear()
    with TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        _write_log(data_dir, "tests/test_bin.py", b"ok\xff\xfe done\n")
        result = read_live_output(data_dir, "tests/test_bin.py")
        assert result is not None
        assert "ok" in result and "done" in result
        assert "�" in result  # replacement character


def test_clear_live_output_removes_directory():
    """clear_live_output deletes the directory and resets the cache."""
    live_output._read_cache.clear()
    with TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        _write_log(data_dir, "tests/test_a.py", b"data\n")
        read_live_output(data_dir, "tests/test_a.py")  # populate the cache
        assert live_output_dir(data_dir).exists()

        clear_live_output(data_dir)
        assert not live_output_dir(data_dir).exists()
        assert live_output._read_cache == {}


def test_clear_live_output_safe_when_absent():
    """clear_live_output does not error when the directory does not exist."""
    with TemporaryDirectory() as tmp:
        clear_live_output(Path(tmp))  # no live_output dir created — must not raise
