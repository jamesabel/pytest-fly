"""Application bootstrap — configures logging and launches the Qt GUI."""

import argparse
from pathlib import Path

from .__version__ import application_name
from .gui import fly_main
from .gui.about_tab.project_info import get_project_info
from .logger import get_logger, init_parent_logger
from .paths import get_default_data_dir
from .preferences import get_pref
from .put_version import detect_put_version

log = get_logger(application_name)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=application_name, description="pytest-fly: pytest runner and observer GUI")
    parser.add_argument("--target", type=Path, default=None, help="Target project directory (the program under test). Overrides the saved preference for this run only.")
    parser.add_argument("--data-dir", type=Path, default=None, help="Override the application data directory (DB, logs). Useful for clean automated runs.")
    parser.add_argument("--auto-start", action="store_true", help="Automatically click the Run button shortly after the window appears.")
    parser.add_argument("--auto-quit-on-done", action="store_true", help="Close the window once the active test run finishes. Pair with --auto-start for unattended runs.")
    return parser.parse_args(argv)


def app_main(argv: list[str] | None = None):
    """Initialize logging and launch the GUI."""
    args = _parse_args(argv)

    init_parent_logger(verbose=get_pref().verbose)

    project_info = get_project_info()
    log.info(f"{project_info.application_name} version {project_info.version}")

    if args.target is not None:
        target = args.target.resolve()
        get_pref().target_project_path = str(target)
        log.info(f"target project path overridden via --target: {target}")

    data_dir = args.data_dir.resolve() if args.data_dir is not None else get_default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    put_info = detect_put_version()
    log.info(f"program under test: {put_info.short_label()} (source={put_info.source}, project_root={put_info.project_root})")

    fly_main(data_dir, auto_start=args.auto_start, auto_quit_on_done=args.auto_quit_on_done)
