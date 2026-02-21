from pathlib import Path
import io

from hashy import get_string_sha256

from coverage import Coverage
from coverage.exceptions import NoDataError, DataError

from ..logger import get_logger
from pytest_fly.__version__ import application_name

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

    coverage_summary_file_path = None
    coverage_summary_file_mtime = None
    for file_path in sorted(Path(coverage_parent_directory).rglob(_coverage_summary_file_name)):
        if file_path.is_file():
            file_mtime = file_path.stat().st_mtime
            if coverage_summary_file_path is None or file_mtime > coverage_summary_file_mtime:
                coverage_summary_file_path = file_path
                coverage_summary_file_mtime = file_mtime

    try:
        if coverage_summary_file_path is not None and len(coverage_string := coverage_summary_file_path.read_text().strip()) > 0:
            coverage_value = float(coverage_string)
    except ValueError as e:
        log.info(f'"{coverage_summary_file_path}",{e}')
    except (FileNotFoundError, PermissionError, IOError) as e:
        log.info(f'"{coverage_summary_file_path}",{e}')

    return coverage_value


log = get_logger(application_name)


class PytestFlyCoverage(Coverage):

    def __init__(self, data_file: Path) -> None:
        super().__init__(data_file, timid=True, concurrency=["thread", "process"], check_preimported=True)
        # avoid: "CoverageWarning: Couldn't parse '...': No source for code: '...'. (couldnt-parse)"
        self._no_warn_slugs.add("couldnt-parse")


def calculate_coverage(test_identifier: str, coverage_parent_directory: Path, write_report: bool) -> float | None:
    """
    Load a collection of coverage files from a directory and calculate the overall coverage.

    :param test_identifier: Test identifier.
    :param coverage_parent_directory: The directory containing the coverage files.
    :param write_report: Whether to write the HTML report.
    :return: The overall coverage as a value between 0.0 and 1.0, or None if no coverage files were found.
    """

    coverage_value = None

    coverage_directory = Path(coverage_parent_directory, "coverage")

    combined_parent_directory = _get_combined_directory(coverage_parent_directory)

    test_identifier_hash = get_string_sha256(test_identifier)
    combined_file_name = f"{get_string_sha256(test_identifier_hash)}.combined"
    combined_file_path = Path(combined_parent_directory, combined_file_name)
    combined_directory = Path(combined_parent_directory, test_identifier_hash)  # HTML report directory

    try:
        coverage_file_paths = sorted(p for p in coverage_directory.rglob("*.coverage", case_sensitive=False))
        coverage_files_as_strings = [str(p) for p in coverage_file_paths]

        cov = PytestFlyCoverage(combined_file_path)
        cov.combine(coverage_files_as_strings, keep=True)
        cov.save()

        output_buffer = io.StringIO()  # unused but required by the API
        coverage_value = cov.report(ignore_errors=True, output_format="total", file=output_buffer) / 100.0  # report returns coverage as a percentage
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

    return coverage_value
