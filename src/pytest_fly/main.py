"""Application bootstrap — configures logging and launches the Qt GUI."""

import argparse
from pathlib import Path

from .__version__ import application_name
from .gui import fly_main
from .gui.about_tab.project_info import get_project_info
from .logger import get_logger, init_parent_logger
from .paths import get_default_data_dir, read_last_target, write_last_target
from .preferences import get_pref, init_preferences_for_put
from .put_version import detect_put_version

log = get_logger(application_name)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=application_name, description="pytest-fly: pytest runner and observer GUI")
    parser.add_argument("--target", type=Path, default=None, help="Target project directory (the program under test). Defaults to the current working directory.")
    parser.add_argument("--data-dir", type=Path, default=None, help="Override the test-results DB directory for this run. Takes precedence over the saved preference and the platform default.")
    parser.add_argument("--auto-start", action="store_true", help="Automatically click the Run button shortly after the window appears.")
    parser.add_argument("--auto-quit-on-done", action="store_true", help="Close the window once the active test run finishes. Pair with --auto-start for unattended runs.")
    return parser.parse_args(argv)


def app_main(argv: list[str] | None = None):
    """Initialize logging and launch the GUI."""
    args = _parse_args(argv)

    # Resolve the PUT first; per-PUT preferences live under <PUT>/.pytest-fly/, so every
    # subsequent pref access (including verbose-flag-driven log init) needs this bound.
    # Precedence: explicit --target > persisted last_target file > cwd.
    if args.target is not None:
        put_path = args.target.resolve()
    else:
        saved = read_last_target()
        put_path = saved.resolve() if saved is not None else Path.cwd()
    init_preferences_for_put(put_path)
    # Persist whichever PUT we just resolved so a no-arg relaunch picks the same one.
    write_last_target(put_path)
    log.info(f"program under test path: {put_path}")

    pref = get_pref()
    init_parent_logger(verbose=pref.verbose)

    project_info = get_project_info()
    log.info(f"{project_info.application_name} version {project_info.version}")

    # Precedence: --data-dir CLI > pref.test_results_db_dir > platform default.
    if args.data_dir is not None:
        data_dir = args.data_dir.resolve()
    elif pref.test_results_db_dir:
        data_dir = Path(pref.test_results_db_dir).resolve()
    else:
        data_dir = get_default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    put_info = detect_put_version(put_path)
    log.info(f"program under test: {put_info.short_label()} (source={put_info.source}, project_root={put_info.project_root})")

    fly_main(data_dir, auto_start=args.auto_start, auto_quit_on_done=args.auto_quit_on_done)
