"""Application bootstrap — configures logging and launches the Qt GUI."""

from balsa import Balsa

from .__version__ import application_name, author
from .gui import fly_main
from .gui.about_tab.project_info import get_project_info
from .logger import get_logger, set_log_directory
from .paths import get_default_data_dir
from .preferences import get_pref
from .put_version import detect_put_version

log = get_logger(application_name)


class FlyLogger(Balsa):
    """Application-level Balsa logger configured from user preferences."""

    def __init__(self):
        pref = get_pref()
        super().__init__(name=application_name, author=author, verbose=pref.verbose, gui=False)


def app_main():
    """Initialize logging and launch the GUI."""
    fly_logger = FlyLogger()
    fly_logger.init_logger()
    set_log_directory(fly_logger.log_directory)

    project_info = get_project_info()
    log.info(f"{project_info.application_name} version {project_info.version}")

    put_info = detect_put_version()
    log.info(f"program under test: {put_info.short_label()} (source={put_info.source}, project_root={put_info.project_root})")

    data_dir = get_default_data_dir()

    fly_main(data_dir)
