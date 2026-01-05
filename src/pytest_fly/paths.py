import os
from pathlib import Path
from platformdirs import user_data_dir
from functools import cache

from .const import PYTEST_FLY_DATA_DIR_STRING
from .__version__ import application_name, author


@cache
def get_default_data_dir() -> Path:
    data_dir = Path(os.environ.get(PYTEST_FLY_DATA_DIR_STRING, Path(user_data_dir(application_name, author))))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir
