"""Tests for file_util.find_most_recent_file."""

import time
from pathlib import Path
from tempfile import TemporaryDirectory

from pytest_fly.file_util import find_most_recent_file


def test_find_most_recent_file():
    """Should return the most recently modified file matching the pattern."""
    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        older = tmp_path / "older.txt"
        older.write_text("old")
        # Ensure a measurable time difference
        time.sleep(0.05)
        newer = tmp_path / "newer.txt"
        newer.write_text("new")

        result = find_most_recent_file(tmp_path, "*.txt")
        assert result == newer


def test_find_most_recent_file_nested():
    """Should find files in subdirectories via rglob."""
    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        sub = tmp_path / "sub"
        sub.mkdir()
        f = sub / "data.txt"
        f.write_text("hello")

        result = find_most_recent_file(tmp_path, "*.txt")
        assert result == f


def test_find_most_recent_file_no_match():
    """Should return None when no files match the pattern."""
    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "file.log").write_text("log")

        result = find_most_recent_file(tmp_path, "*.txt")
        assert result is None


def test_find_most_recent_file_empty_dir():
    """Should return None for an empty directory."""
    with TemporaryDirectory() as tmp:
        result = find_most_recent_file(Path(tmp), "*.txt")
        assert result is None
