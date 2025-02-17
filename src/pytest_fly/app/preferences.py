from pathlib import Path

from attr import attrib, attrs
from pref import Pref, PrefOrderedSet
from appdirs import user_data_dir

from ..__version__ import application_name, author

preferences_file_name = f"{application_name}_preferences.db"


@attrs
class FlyPreferences(Pref):
    window_x: int = attrib(default=-1)
    window_y: int = attrib(default=-1)
    window_width: int = attrib(default=-1)
    window_height: int = attrib(default=-1)
    verbose: bool = attrib(default=False)
    csv_dump_path: str = attrib(default=str(Path(user_data_dir(application_name, author), f"{application_name}.csv")))


def get_pref() -> FlyPreferences:
    return FlyPreferences(application_name, author, file_name=preferences_file_name)


class PrefSplits(PrefOrderedSet):
    def __init__(self):
        super().__init__(application_name, author, "split", preferences_file_name)


def get_splits() -> PrefOrderedSet:
    return PrefSplits()
