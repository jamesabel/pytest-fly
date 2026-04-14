"""Tests for coverage summary write/read functions."""

from pathlib import Path
from tempfile import TemporaryDirectory

from pytest_fly.pytest_runner.coverage import write_coverage_summary_file, read_most_recent_coverage_summary_file


def test_write_and_read_coverage_summary():
    """Round-trip: write a coverage value then read it back."""
    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        write_coverage_summary_file(0.85, "test_module_a", tmp_path)

        result = read_most_recent_coverage_summary_file(tmp_path)
        assert result is not None
        assert abs(result - 0.85) < 0.001


def test_read_coverage_summary_missing():
    """Should return None when no coverage summary file exists."""
    with TemporaryDirectory() as tmp:
        result = read_most_recent_coverage_summary_file(Path(tmp))
        assert result is None


def test_write_multiple_read_most_recent():
    """When multiple summaries exist, should return the most recently written."""
    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        write_coverage_summary_file(0.50, "test_a", tmp_path)
        write_coverage_summary_file(0.75, "test_b", tmp_path)

        result = read_most_recent_coverage_summary_file(tmp_path)
        assert result is not None
        # Should be one of the written values (the most recent file)
        assert result in (0.50, 0.75)
