import os
from pathlib import Path

from typeguard import typechecked

from pytest_fly.platform import mk_dirs
from pytest_fly.const import PYTEST_FLY_DATA_DIR_STRING


@typechecked()
def get_temp_dir(test_name: str) -> Path:
    temp_parent = Path(os.environ.get(PYTEST_FLY_DATA_DIR_STRING, "temp"))
    temp_dir = Path(temp_parent, test_name)
    mk_dirs(temp_dir, True)
    return temp_dir
