import webbrowser
from pathlib import Path

from typeguard import typechecked

from ....controller.coverage import get_combined_coverage_file_path
from ....logger import get_logger
from .....__version__ import application_name

log = get_logger(application_name)


class ViewCoverage:

    @typechecked
    def __init__(self, coverage_parent_directory: Path):
        self.coverage_parent_directory = coverage_parent_directory

    def view(self):
        if self.coverage_parent_directory.exists():

            combined_coverage_file_path = get_combined_coverage_file_path(self.coverage_parent_directory)
            if combined_coverage_file_path.exists():
                html_report_directory = Path(self.coverage_parent_directory, "html")
                html_file_path = Path(html_report_directory, "index.html")
                webbrowser.open(html_file_path.as_uri())  # load the coverage report in the default browser
            else:
                log.warning(f'Combined coverage file does not exist: "{combined_coverage_file_path}"')
        else:
            log.warning(f'Coverage parent directory does not exist: "{self.coverage_parent_directory}"')
            return
