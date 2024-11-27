from attr import attrib, attrs

from pref import Pref

from ..__version__ import application_name, author


@attrs
class Preferences(Pref):
    window_x: int = attrib(default=-1)
    window_y: int = attrib(default=-1)
    window_width: int = attrib(default=-1)
    window_height: int = attrib(default=-1)

    def __attrs_post_init__(self):
        # pytest-fly.db is used to store the test run data. By default, pref would have used pytest-fly.db as the preferences DB file name, so we need to use a different name.
        self.file_name = f"{application_name}_preferences.db"
        super().__attrs_post_init__()


def get_pref() -> Preferences:
    return Preferences(application_name, author)
