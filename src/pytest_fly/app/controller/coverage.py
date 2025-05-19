import time
import random
from pathlib import Path
import io

from coverage import Coverage
from coverage.exceptions import NoDataError

from ..logger import get_logger
from ...__version__ import application_name
from ..model.os import rm_file

log = get_logger(application_name)

_combined_coverage_file_name = "combined.coverage"
_combined_lock_file_name = "combined.lock"


def get_combined_coverage_file_path(coverage_parent_directory: Path) -> Path:
    """
    Get the path to the combined coverage file.

    :param coverage_parent_directory: The directory containing the coverage files.
    :return: The path to the combined coverage file.
    """
    return Path(coverage_parent_directory, _combined_coverage_file_name)


class PytestFlyCoverage(Coverage):

    def __init__(self, data_file: Path) -> None:
        super().__init__(data_file, timid=True, concurrency=["thread", "process"], check_preimported=True)
        # avoid: "CoverageWarning: Couldn't parse '...': No source for code: '...'. (couldnt-parse)"
        self._no_warn_slugs.add("couldnt-parse")


def calculate_coverage(coverage_parent_directory: Path) -> float | None:
    """
    Load a collection of coverage files from a directory and calculate the overall coverage.

    :param coverage_parent_directory: The directory containing the coverage files.
    :return: The overall coverage as a value between 0.0 and 1.0, or None if no coverage files were found.
    """

    coverage_value = None

    coverage_directory = Path(coverage_parent_directory, "coverage")
    coverage_file_paths = sorted(p for p in coverage_directory.rglob("*.coverage", case_sensitive=False))
    coverage_files_as_strings = [str(p) for p in coverage_file_paths]

    combined_path = get_combined_coverage_file_path(coverage_parent_directory)
    combined_lock_path = coverage_parent_directory / _combined_lock_file_name

    # shared files are written to the parent directory, so we need a lock
    timeout = 100.0  # seconds
    start = time.time()
    lock_acquired = False
    while not lock_acquired and time.time() - start < timeout:
        try:
            combined_lock_path.touch(exist_ok=False)
            lock_acquired = True
        except (FileExistsError, PermissionError):
            wait_time = 0.5 + random.random()
            log.info(f'"{combined_lock_path}" is locked, waiting {wait_time} seconds')
            time.sleep(wait_time)

    if lock_acquired:
        rm_file(combined_path)
        try:
            cov = PytestFlyCoverage(combined_path)
            cov.combine(coverage_files_as_strings, keep=True)
            cov.save()

            output_buffer = io.StringIO()  # unused but required by the API
            coverage_value = cov.report(ignore_errors=True, output_format="total", file=output_buffer) / 100.0  # report returns coverage as a percentage
            html_directory = Path(coverage_parent_directory, "html")
            cov.html_report(directory=str(html_directory), ignore_errors=True)

        except NoDataError:
            # when we start, we may not have any coverage data
            pass
    else:
        log.warning(f"Failed to acquire lock on {combined_lock_path} within {timeout} seconds.")

    # remove the lock file
    combined_lock_path.unlink(missing_ok=True)

    return coverage_value
