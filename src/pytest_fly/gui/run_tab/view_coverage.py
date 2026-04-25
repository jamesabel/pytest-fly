"""Opens the most recent HTML coverage report in the user's default browser."""

import webbrowser
from pathlib import Path

from typeguard import typechecked

from pytest_fly.__version__ import application_name
from pytest_fly.file_util import find_most_recent_file
from pytest_fly.logger import get_logger

log = get_logger(application_name)


class ViewCoverage:
    """Opens the most recent HTML coverage report in the user's default browser."""

    @typechecked()
    def __init__(self, coverage_parent_directory: Path):
        self.coverage_parent_directory = coverage_parent_directory

    def view(self):
        """Locate the newest ``index.html`` under the coverage directory and open it."""
        if self.coverage_parent_directory.exists():
            combined_coverage_html_file_path = find_most_recent_file(self.coverage_parent_directory, "index.html")
            if combined_coverage_html_file_path is not None:
                webbrowser.open(combined_coverage_html_file_path.as_uri())
        else:
            log.warning(f'Coverage parent directory does not exist: "{self.coverage_parent_directory}"')
