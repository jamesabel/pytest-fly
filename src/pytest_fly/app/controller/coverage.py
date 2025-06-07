from pathlib import Path
import io

from hashy import get_string_sha256

from coverage import Coverage
from coverage.exceptions import NoDataError, DataError

from ..logger import get_logger
from ...__version__ import application_name


log = get_logger(application_name)


class PytestFlyCoverage(Coverage):

    def __init__(self, data_file: Path) -> None:
        super().__init__(data_file, timid=True, concurrency=["thread", "process"], check_preimported=True)
        # avoid: "CoverageWarning: Couldn't parse '...': No source for code: '...'. (couldnt-parse)"
        self._no_warn_slugs.add("couldnt-parse")


def calculate_coverage(test_identifier: str, coverage_parent_directory: Path) -> float | None:
    """
    Load a collection of coverage files from a directory and calculate the overall coverage.

    :param test_identifier: Test identifier.
    :param coverage_parent_directory: The directory containing the coverage files.
    :return: The overall coverage as a value between 0.0 and 1.0, or None if no coverage files were found.
    """

    coverage_value = None

    coverage_directory = Path(coverage_parent_directory, "coverage")
    coverage_file_paths = sorted(p for p in coverage_directory.rglob("*.coverage", case_sensitive=False))
    coverage_files_as_strings = [str(p) for p in coverage_file_paths]

    combined_parent_directory = Path(coverage_parent_directory, "combined")

    test_identifier_hash = get_string_sha256(test_identifier)
    combined_file_name = f"{get_string_sha256(test_identifier_hash)}.combined"
    combined_file_path = Path(combined_parent_directory, combined_file_name)
    combined_directory = Path(combined_parent_directory, test_identifier_hash)  # HTML report directory

    try:
        cov = PytestFlyCoverage(combined_file_path)
        cov.combine(coverage_files_as_strings, keep=True)
        cov.save()

        output_buffer = io.StringIO()  # unused but required by the API
        coverage_value = cov.report(ignore_errors=True, output_format="total", file=output_buffer) / 100.0  # report returns coverage as a percentage
        cov.html_report(directory=str(combined_directory), ignore_errors=True)
    except NoDataError:
        # when we start, we may not have any coverage data
        pass
    except DataError as e:
        log.info(f"{e}")

    return coverage_value
