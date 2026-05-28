"""Resolve the application data directory and persist the last-selected PUT path."""

import os
from functools import cache
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

from .__version__ import application_name, author
from .const import PYTEST_FLY_DATA_DIR_STRING

_LAST_TARGET_FILE_NAME = "last_target.txt"


@cache
def get_default_data_dir() -> Path:
    """Return the application data directory, creating it if necessary.

    Checks the ``PYTEST_FLY_DATA_DIR`` environment variable first; falls back
    to the platform-standard user data directory (via ``platformdirs``).
    """
    data_dir = Path(os.environ.get(PYTEST_FLY_DATA_DIR_STRING, Path(user_data_dir(application_name, author))))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def _last_target_file() -> Path:
    return Path(user_config_dir(application_name, author), _LAST_TARGET_FILE_NAME)


def read_last_target() -> Path | None:
    """Return the most recently selected PUT path, or ``None`` if none has been saved.

    Per-PUT preferences live inside the PUT, so the "which PUT to open" choice
    can't itself be stored there.  A small text file in the user config dir
    persists the user's selection across launches.
    """
    path = _last_target_file()
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    return Path(text)


def write_last_target(target: Path) -> None:
    """Persist *target* as the last-selected PUT path."""
    path = _last_target_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(target.resolve()), encoding="utf-8")
