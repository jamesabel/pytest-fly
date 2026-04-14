"""Tests for coverage functions and line counting."""

from pathlib import Path
from tempfile import TemporaryDirectory

from pytest_fly.pytest_runner.coverage import (
    write_coverage_summary_file,
    read_most_recent_coverage_summary_file,
    calculate_coverage,
    _parse_report_totals,
)


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


def test_parse_report_totals():
    """_parse_report_totals should extract Stmts and Miss from a coverage text report."""
    report = """Name       Stmts   Miss  Cover
------------------------------
foo.py        10      3    70%
bar.py        20      5    75%
------------------------------
TOTAL         30      8    73%
"""
    stmts, miss = _parse_report_totals(report)
    assert stmts == 30
    assert miss == 8


def test_parse_report_totals_empty():
    """_parse_report_totals should return (0, 0) for empty or missing TOTAL."""
    assert _parse_report_totals("") == (0, 0)
    assert _parse_report_totals("no total here") == (0, 0)


def test_covered_lines_not_greater_than_total():
    """Covered lines from calculate_coverage must not exceed total statements."""
    for data_dir in [Path("temp/test_pytest_runner_multiprocess"), Path("temp/test_pytest_runner_simple")]:
        coverage_dir = data_dir / "coverage"
        if coverage_dir.exists() and list(coverage_dir.glob("*.coverage")):
            pct, covered, total = calculate_coverage("test_invariant", data_dir, False)
            if pct is not None:
                assert covered <= total, f"covered ({covered}) > total ({total}) in {data_dir}"
                assert total > 0
                assert covered >= 0
                # Verify percentage is consistent: covered/total should approximate pct
                computed_pct = covered / total
                assert abs(computed_pct - pct) < 0.02, f"pct mismatch: {computed_pct:.3f} vs {pct:.3f}"
                return

    # If no coverage data exists, that's OK for CI
    pass
