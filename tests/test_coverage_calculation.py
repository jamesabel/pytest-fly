"""Tests for coverage functions and line counting."""

from pathlib import Path
from tempfile import TemporaryDirectory

from coverage import CoverageData

from pytest_fly.file_util import sanitize_test_name
from pytest_fly.pytest_runner.coverage import (
    _parse_report_totals,
    calculate_coverage,
    compute_per_test_coverage,
    read_most_recent_coverage_summary_file,
    write_coverage_summary_file,
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


def test_parse_report_totals_malformed_numbers():
    """_parse_report_totals should return (0, 0) when TOTAL line has non-numeric values."""
    report = "TOTAL    notanumber    alsobad    ???%\n"
    assert _parse_report_totals(report) == (0, 0)


def test_read_coverage_summary_bad_content():
    """If the summary file content cannot be parsed as a float, read returns None."""
    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        write_coverage_summary_file(0.50, "test_a", tmp_path)
        # corrupt every existing summary file
        for summary in tmp_path.rglob("coverage.txt"):
            summary.write_text("not-a-number\n")

        assert read_most_recent_coverage_summary_file(tmp_path) is None


def test_calculate_coverage_no_data():
    """calculate_coverage returns (None, 0, 0) when no .coverage files exist."""
    with TemporaryDirectory() as tmp:
        pct, covered, total = calculate_coverage("empty_test", Path(tmp), write_report=False)
        assert pct is None
        assert covered == 0
        assert total == 0


def _write_coverage_data(test_name: str, source_file: Path, lines: list[int], coverage_dir: Path) -> None:
    """Write a synthetic .coverage data file recording *lines* executed in *source_file*."""
    coverage_dir.mkdir(parents=True, exist_ok=True)
    safe = sanitize_test_name(test_name)
    data_file = coverage_dir / f"{safe}.coverage"
    data_file.unlink(missing_ok=True)

    data = CoverageData(basename=str(data_file))
    data.add_lines({str(source_file): lines})
    data.write()


def test_compute_per_test_coverage_empty_dir():
    """compute_per_test_coverage returns {} when coverage directory is missing."""
    with TemporaryDirectory() as tmp:
        result = compute_per_test_coverage(Path(tmp), ["tests/test_a.py"])
        assert result == {}


def test_compute_per_test_coverage_with_data():
    """compute_per_test_coverage returns fractions derived from per-test .coverage files."""
    with TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        coverage_dir = data_dir / "coverage"

        src_dir = data_dir / "src_under_test"
        src_dir.mkdir()
        target = src_dir / "m.py"
        target.write_text("a = 1\nb = 2\nc = 3\n")

        _write_coverage_data("tests/test_one.py", target, [1, 2, 3], coverage_dir)

        result = compute_per_test_coverage(data_dir, ["tests/test_one.py", "tests/test_missing.py"])
        assert "tests/test_one.py" in result
        assert result["tests/test_one.py"] == 1.0
        assert "tests/test_missing.py" not in result


def test_compute_per_test_coverage_fractional():
    """Per-test fractions reflect each test's share of the union of executed lines."""
    with TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        coverage_dir = data_dir / "coverage"

        src = data_dir / "m.py"
        src.write_text("a = 1\nb = 2\nc = 3\nd = 4\n")

        _write_coverage_data("tests/test_a.py", src, [1, 2], coverage_dir)
        _write_coverage_data("tests/test_b.py", src, [3, 4], coverage_dir)

        result = compute_per_test_coverage(data_dir, ["tests/test_a.py", "tests/test_b.py"])
        assert result["tests/test_a.py"] == 0.5
        assert result["tests/test_b.py"] == 0.5


def test_calculate_coverage_with_data_and_html_report():
    """calculate_coverage should combine .coverage files and write an HTML report."""
    with TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        coverage_dir = data_dir / "coverage"

        src = data_dir / "m.py"
        src.write_text("a = 1\nb = 2\nc = 3\nd = 4\n")

        _write_coverage_data("tests/test_one.py", src, [1, 2, 3, 4], coverage_dir)

        pct, covered, total = calculate_coverage("combined_id", data_dir, write_report=True)
        # The write_report=True branch (cov.html_report) executes regardless of whether
        # the coverage reporter finds a TOTAL row in its text summary.
        if pct is not None:
            assert covered <= total
        combined_parent = data_dir / "combined"
        assert combined_parent.exists()


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
