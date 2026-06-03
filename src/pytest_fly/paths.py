"""Resolve the application data directory.

The program-under-test (PUT) is always the directory pytest-fly is launched from
(or an explicit ``--target``); there is no global "remembered target" pointer, so
configuration stays local to each project rather than persisting per-user.
"""

import os
from functools import cache
from pathlib import Path

from platformdirs import user_data_dir

from .__version__ import application_name, author
from .const import PYTEST_FLY_DATA_DIR_STRING


@cache
def get_default_data_dir() -> Path:
    """Return the application data directory, creating it if necessary.

    Checks the ``PYTEST_FLY_DATA_DIR`` environment variable first; falls back
    to the platform-standard user data directory (via ``platformdirs``).
    """
    data_dir = Path(os.environ.get(PYTEST_FLY_DATA_DIR_STRING, Path(user_data_dir(application_name, author))))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir
