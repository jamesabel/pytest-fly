"""Additional coverage for per-test coverage edge cases in :mod:`pytest_fly.pytest_runner.coverage`.

Uses the ``tmp_path`` fixture rather than ``TemporaryDirectory`` because the coverage
library can keep a handle on a (corrupt) ``.coverage`` file briefly, which would make an
eager context-manager cleanup fail on Windows; pytest's fixture teardown tolerates that.
"""

from pytest_fly.file_util import sanitize_test_name
from pytest_fly.pytest_runner.coverage import compute_per_test_coverage


def test_compute_per_test_coverage_missing_dir(tmp_path):
    """No coverage directory -> empty mapping."""
    assert compute_per_test_coverage(tmp_path, ["tests/test_a.py"]) == {}


def test_compute_per_test_coverage_no_matching_files(tmp_path):
    """Coverage dir exists but no per-test files match -> empty mapping (total lines == 0)."""
    (tmp_path / "coverage").mkdir()
    assert compute_per_test_coverage(tmp_path, ["tests/test_a.py"]) == {}


def test_compute_per_test_coverage_corrupt_file_is_skipped(tmp_path):
    """A corrupt .coverage file is skipped (load error swallowed) and yields no entry."""
    cov_dir = tmp_path / "coverage"
    cov_dir.mkdir()
    bad = cov_dir / f"{sanitize_test_name('tests/test_a.py')}.coverage"
    bad.write_text("this is not a coverage sqlite db")
    assert compute_per_test_coverage(tmp_path, ["tests/test_a.py"]) == {}
