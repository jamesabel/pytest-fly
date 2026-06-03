"""Resolve pytest-fly's local storage paths.

pytest-fly keeps everything it produces — preferences, logs, and the test-results
database — under ``<workspace>/.pytest-fly/``, where the *workspace* is the directory
pytest-fly was launched from.  Nothing lives in the per-user "appdir" space.

The program-under-test (PUT) — the project whose tests are run — is a separate,
user-configurable preference (see :func:`pytest_fly.preferences.get_active_put_path`)
and does *not* affect where this storage lives.  Decoupling the two means the PUT can be
changed freely without moving the preference DB or needing a global "remembered target"
pointer.
"""

import os
from pathlib import Path

from .__version__ import application_name
from .const import PYTEST_FLY_DATA_DIR_STRING, PYTEST_FLY_WORKSPACE_STRING

fly_dir_name = f".{application_name}"  # ".pytest-fly" — hidden storage dir inside the workspace
preferences_file_name = "preferences.db"
_log_subdir_name = "logs"

_workspace_dir: Path | None = None


def init_workspace(workspace_dir: Path) -> None:
    """Bind pytest-fly's storage root to *workspace_dir* (the launch directory).

    Also exported via the ``PYTEST_FLY_WORKSPACE`` environment variable so spawned child
    processes — which re-import this module with no in-process binding — resolve the same
    storage paths (e.g. for their per-child log files).
    """
    global _workspace_dir
    _workspace_dir = workspace_dir.resolve()
    os.environ[PYTEST_FLY_WORKSPACE_STRING] = str(_workspace_dir)


def get_workspace_dir() -> Path:
    """Return the workspace directory bound via :func:`init_workspace`.

    In a spawned child the in-process binding is absent, so fall back to the
    ``PYTEST_FLY_WORKSPACE`` environment variable inherited from the parent.
    """
    global _workspace_dir
    if _workspace_dir is None:
        env = os.environ.get(PYTEST_FLY_WORKSPACE_STRING)
        if not env:
            raise RuntimeError("init_workspace() must be called before resolving storage paths")
        _workspace_dir = Path(env)
    return _workspace_dir


def get_fly_data_dir() -> Path:
    """Return ``<workspace>/.pytest-fly/`` — the root for preferences, logs, and the results DB."""
    fly_dir = Path(get_workspace_dir(), fly_dir_name)
    fly_dir.mkdir(parents=True, exist_ok=True)
    return fly_dir


def get_preferences_db_path() -> Path:
    """Return the path to the workspace-local preferences DB."""
    return Path(get_fly_data_dir(), preferences_file_name)


def get_log_dir() -> Path:
    """Return ``<workspace>/.pytest-fly/logs/`` — shared by the parent and spawn children."""
    log_dir = Path(get_fly_data_dir(), _log_subdir_name)
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_default_data_dir() -> Path:
    """Return the default directory for the test-results DB, creating it if necessary.

    The ``PYTEST_FLY_DATA_DIR`` environment variable overrides it (used by tests / CI);
    otherwise it lives under ``<workspace>/.pytest-fly/`` like everything else.
    """
    env = os.environ.get(PYTEST_FLY_DATA_DIR_STRING)
    data_dir = Path(env) if env else get_fly_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir
