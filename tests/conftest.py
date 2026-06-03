import faulthandler
import multiprocessing
import os
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from pytest_fly.preferences import init_preferences_for_put

# Force the 'spawn' multiprocessing start method on all platforms. pytest-fly's controller is
# multi-threaded (a worker pool plus the stall watchdog) and starts test subprocesses; on POSIX
# the default 'fork' lets a child inherit a lock held by another thread at fork time and deadlock.
# Windows — the primary dev/test platform — already uses 'spawn', so this aligns POSIX (CI) with
# the known-good path. Must run before any Process is created, hence at conftest import time.
try:
    multiprocessing.set_start_method("spawn", force=True)
except RuntimeError:
    pass

# CI hang safety net: if the suite ever wedges, dump every thread's traceback and abort rather
# than running until GitHub's 6-hour limit. Generous timeout so a slow (spawn) run never trips it.
if os.environ.get("CI"):
    faulthandler.dump_traceback_later(1200, exit=True)

pytest_plugins = "pytester"


@pytest.fixture(scope="session", autouse=True)
def _bind_test_prefs(tmp_path_factory):
    """Bind pref storage to a session-scoped tmp PUT so tests never touch the user's real prefs.

    Per-test fixtures (e.g. the ordering-aspects suite) can call
    :func:`init_preferences_for_put` again to redirect into their own tmp dirs.
    """
    init_preferences_for_put(tmp_path_factory.mktemp("pytest_fly_test_prefs"))


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="session", autouse=True)
def make_many_tests():
    """
    Makes many tests in order to test pytest_fly itself for things like scrollable windows and saving off Window dimensions that aren't off the screen.
    """
    number_of_tests = 2  # should be like 40, but set to a lower number for interactive debug
    test_parent_glob = list(Path().glob("test*"))
    assert len(test_parent_glob) == 1
    test_parent = test_parent_glob[0]
    many_test_dir = Path(test_parent, "tests_many")
    if not many_test_dir.exists():
        print(f'making "{many_test_dir}"')
        many_test_dir.mkdir(exist_ok=True, parents=True)
        # more than can fit in a window without scroll bars
        for test_number in range(number_of_tests):
            test_file = Path(many_test_dir, f"test_many_{test_number:03d}.py")
            lines = [f"def test_many_{test_number}():", "    print(sum([x for x in range((int(1E7)))]))", "    assert True\n"]
            test_file.write_text("\n".join(lines))
