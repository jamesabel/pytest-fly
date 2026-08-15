"""Opens the most recent HTML coverage report in the user's default browser."""

import webbrowser
from pathlib import Path

from typeguard import typechecked

from ..file_util import find_most_recent_file
from ..logger import get_logger

log = get_logger()


class ViewCoverage:
    """Opens the most recent HTML coverage report in the user's default browser."""

    @typechecked()
    def __init__(self, coverage_parent_directory: Path):
        self.coverage_parent_directory = coverage_parent_directory

    def view(self) -> bool:
        """Locate the newest ``index.html`` under the coverage directory and open it.

        :return: ``True`` if a report was found and opened, ``False`` otherwise (so the
            caller can tell the user instead of silently doing nothing).
        """
        if self.coverage_parent_directory.exists():
            combined_coverage_html_file_path = find_most_recent_file(self.coverage_parent_directory, "index.html")
            if combined_coverage_html_file_path is not None:
                webbrowser.open(combined_coverage_html_file_path.as_uri())
                return True
            log.warning(f'No coverage report (index.html) found under: "{self.coverage_parent_directory}"')
        else:
            log.warning(f'Coverage parent directory does not exist: "{self.coverage_parent_directory}"')
        return False
