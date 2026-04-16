"""Application bootstrap — configures logging and launches the Qt GUI."""

from balsa import Balsa

from .__version__ import application_name, author
from .gui import fly_main
from .logger import get_logger, set_log_directory
from .paths import get_default_data_dir
from .preferences import get_pref

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

    data_dir = get_default_data_dir()

    fly_main(data_dir)
