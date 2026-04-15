import io
from pathlib import Path

from coverage import Coverage
from coverage.exceptions import DataError, NoDataError
from hashy import get_string_sha256

from pytest_fly.__version__ import application_name

from ..file_util import find_most_recent_file, sanitize_test_name
from ..logger import get_logger

log = get_logger(application_name)

_coverage_summary_file_name = "coverage.txt"


def _get_combined_directory(coverage_parent_directory: Path) -> Path:
    """
    Get the directory where combined coverage files are stored.

    :param coverage_parent_directory: The parent directory for coverage files.
    :return: The path to the combined directory.
    """
    d = Path(coverage_parent_directory, "combined")
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_coverage_summary_file(coverage_value: float, test_identifier: str, coverage_parent_directory: Path) -> None:
    """
    Write the coverage summary to a file in the specified directory.
    """
    test_identifier_hash = get_string_sha256(test_identifier)
    d = Path(_get_combined_directory(coverage_parent_directory), test_identifier_hash)
    d.mkdir(parents=True, exist_ok=True)
    Path(d, _coverage_summary_file_name).write_text(f"{coverage_value}\n")


def read_most_recent_coverage_summary_file(coverage_parent_directory: Path) -> float | None:
    """
    Read the most recent coverage summary file from the specified directory.

    :param coverage_parent_directory: The directory containing the coverage summary files.
    :return: The coverage value as a float, or None if no valid coverage file is found.
    """

    coverage_value = None

    coverage_summary_file_path = find_most_recent_file(Path(coverage_parent_directory), _coverage_summary_file_name)

    try:
        if coverage_summary_file_path is not None and len(coverage_string := coverage_summary_file_path.read_text().strip()) > 0:
            coverage_value = float(coverage_string)
    except ValueError as e:
        log.info(f'"{coverage_summary_file_path}",{e}')
    except (FileNotFoundError, PermissionError, IOError) as e:
        log.info(f'"{coverage_summary_file_path}",{e}')

    return coverage_value


class PytestFlyCoverage(Coverage):
    def __init__(self, data_file: Path, **kwargs) -> None:
        super().__init__(data_file, timid=True, concurrency=["thread", "multiprocessing"], check_preimported=True, **kwargs)
        # avoid: "CoverageWarning: Couldn't parse '...': No source for code: '...'. (couldnt-parse)"
        self._no_warn_slugs.add("couldnt-parse")


def _parse_report_totals(report_output: str) -> tuple[int, int]:
    """Parse the TOTAL line from a coverage text report to get (statements, missing)."""
    for line in report_output.splitlines():
        if line.startswith("TOTAL"):
            parts = line.split()
            if len(parts) >= 3:
                try:
                    return int(parts[1]), int(parts[2])
                except (ValueError, IndexError):
                    pass
    return 0, 0


def calculate_coverage(test_identifier: str, coverage_parent_directory: Path, write_report: bool) -> tuple[float | None, int, int]:
    """
    Load a collection of coverage files from a directory and calculate the overall coverage.

    :param test_identifier: Test identifier.
    :param coverage_parent_directory: The directory containing the coverage files.
    :param write_report: Whether to write the HTML report.
    :return: Tuple of (overall coverage as 0.0-1.0 or None, covered statements, total statements).
    """

    coverage_value = None
    covered_statements = 0
    total_statements = 0

    coverage_directory = Path(coverage_parent_directory, "coverage")

    combined_parent_directory = _get_combined_directory(coverage_parent_directory)

    test_identifier_hash = get_string_sha256(test_identifier)
    combined_file_name = f"{test_identifier_hash}.combined"
    combined_file_path = Path(combined_parent_directory, combined_file_name)
    combined_directory = Path(combined_parent_directory, test_identifier_hash)  # HTML report directory

    try:
        coverage_file_paths = sorted(p for p in coverage_directory.rglob("*.coverage", case_sensitive=False))
        coverage_files_as_strings = [str(p) for p in coverage_file_paths]

        cov = PytestFlyCoverage(combined_file_path)
        cov.combine(coverage_files_as_strings, keep=True)
        cov.save()

        # Get percentage from total-only report
        total_buffer = io.StringIO()
        coverage_value = cov.report(ignore_errors=True, output_format="total", file=total_buffer) / 100.0

        # Get statement counts from the full text report
        report_buffer = io.StringIO()
        cov.report(ignore_errors=True, file=report_buffer)
        total_statements, missing = _parse_report_totals(report_buffer.getvalue())
        covered_statements = total_statements - missing

        write_coverage_summary_file(coverage_value, test_identifier, coverage_parent_directory)
        if write_report:
            cov.html_report(directory=str(combined_directory), ignore_errors=True)
    except NoDataError:
        # when we start, we may not have any coverage data
        pass
    except DataError as e:
        log.info(f"{test_identifier},{e}")
    except PermissionError as e:
        log.info(f"{test_identifier},{e}")

    return coverage_value, covered_statements, total_statements


def compute_per_test_coverage(data_dir: Path, test_names: list[str]) -> dict[str, float]:
    """Compute per-test coverage fractions from stored per-test coverage files.

    Loads each test's individual ``.coverage`` file, counts executed lines,
    and divides by the total lines across all tests to produce a fraction.

    :param data_dir: The application data directory containing the ``coverage/`` subdirectory.
    :param test_names: List of test node_ids (e.g. ``"tests/test_foo.py"``).
    :return: Mapping of test name to coverage fraction (0.0--1.0).  Tests
             without a coverage file are omitted.
    """
    coverage_dir = Path(data_dir, "coverage")
    if not coverage_dir.exists():
        return {}

    # Load each test's coverage data and count executed lines
    per_test_lines: dict[str, int] = {}
    all_file_lines: dict[str, set[int]] = {}  # source_file -> set of executed line numbers (union across all tests)

    for test_name in test_names:
        safe_name = sanitize_test_name(test_name)
        cov_file = coverage_dir / f"{safe_name}.coverage"
        if not cov_file.exists():
            continue
        try:
            cov = Coverage(cov_file)
            cov.load()
            data = cov.get_data()
            executed = 0
            for f in data.measured_files():
                lines = data.lines(f) or []
                executed += len(lines)
                all_file_lines.setdefault(f, set()).update(lines)
            per_test_lines[test_name] = executed
        except Exception as e:
            log.info(f"per-test coverage load for {test_name} failed: {e}")

    total_lines = sum(len(lines) for lines in all_file_lines.values())
    if total_lines == 0:
        return {}

    return {name: executed / total_lines for name, executed in per_test_lines.items()}
