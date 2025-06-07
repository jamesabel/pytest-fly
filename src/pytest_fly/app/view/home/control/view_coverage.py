import webbrowser
from pathlib import Path

from typeguard import typechecked

from ....logger import get_logger
from .....__version__ import application_name

log = get_logger(application_name)


class ViewCoverage:

    @typechecked
    def __init__(self, coverage_parent_directory: Path):
        self.coverage_parent_directory = coverage_parent_directory

    def view(self):
        if self.coverage_parent_directory.exists():

            # find the most recent combined coverage file
            combined_coverage_html_file_path = None
            combined_coverage_file_mtime = None
            for file_path in sorted(self.coverage_parent_directory.rglob("index.html"), reverse=True):
                if file_path.is_file():
                    m_time = file_path.stat().st_mtime
                    if combined_coverage_file_mtime is None or m_time > combined_coverage_file_mtime:
                        combined_coverage_html_file_path = file_path
                        combined_coverage_file_mtime = m_time

            if combined_coverage_html_file_path is not None:
                webbrowser.open(combined_coverage_html_file_path.as_uri())  # load the coverage report in the default browser
        else:
            log.warning(f'Coverage parent directory does not exist: "{self.coverage_parent_directory}"')
            return
