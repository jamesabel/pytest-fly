"""Application bootstrap — configures logging and launches the Qt GUI."""

from .__version__ import application_name
from .gui import fly_main
from .gui.about_tab.project_info import get_project_info
from .logger import get_logger, init_parent_logger
from .paths import get_default_data_dir
from .preferences import get_pref
from .put_version import detect_put_version

log = get_logger(application_name)


def app_main():
    """Initialize logging and launch the GUI."""
    init_parent_logger(verbose=get_pref().verbose)

    project_info = get_project_info()
    log.info(f"{project_info.application_name} version {project_info.version}")

    put_info = detect_put_version()
    log.info(f"program under test: {put_info.short_label()} (source={put_info.source}, project_root={put_info.project_root})")

    fly_main(get_default_data_dir())
