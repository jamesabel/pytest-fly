import faulthandler
import multiprocessing
import os
import sys
import tempfile
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


def pytest_configure(config: pytest.Config) -> None:
    """On Windows, route pytest's temp dirs to a fixed basetemp.

    pytest's default temp scheme creates a ``pytest-current`` *directory* symlink and prunes
    numbered run dirs as an atexit cleanup. On Windows that cleanup calls ``Path.unlink()`` on the
    directory symlink, which raises ``PermissionError`` (WinError 5) — directory symlinks require
    ``rmdir`` — producing a noisy "Exception ignored in atexit callback" after every run and, once
    the symlink gets stuck, leaking numbered run dirs. Giving pytest an explicit ``--basetemp``
    makes it use that dir directly and skip the numbered-dir + ``pytest-current`` symlink machinery
    entirely, so the failing path never runs. Scoped to Windows so Linux/CI behavior is unchanged;
    an explicit ``--basetemp`` on the command line is respected.

    The basetemp lives under the system temp dir (not in the repo) so that tests which create a
    fake project in ``tmp_path`` and probe its surroundings — e.g. PUT git-version detection that
    walks parent dirs for ``.git`` — don't accidentally pick up this repo's ``.git``.
    """
    if sys.platform != "win32" or config.option.basetemp:
        return
    basetemp = Path(tempfile.gettempdir()) / "pytest_fly_basetemp"
    config.option.basetemp = str(basetemp)
    # The tmp-path factory captured the (then-empty) option in its own tryfirst pytest_configure,
    # which runs before this hook. getbasetemp() is lazy, so pushing the resolved path onto the
    # live factory before any temp dir is created still takes effect.
    factory = getattr(config, "_tmp_path_factory", None)
    if factory is not None and getattr(factory, "_basetemp", None) is None:
        factory._given_basetemp = basetemp.resolve()


@pytest.fixture(scope="session", autouse=True)
def _bind_test_prefs(tmp_path_factory):
    """Bind pref storage to a session-scoped tmp PUT so tests never touch the user's real prefs.

    Per-test fixtures (e.g. the ordering-aspects suite) can call
    :func:`init_preferences_for_put` again to redirect into their own tmp dirs.
    """
    init_preferences_for_put(tmp_path_factory.mktemp("pytest_fly_test_prefs"))


@pytest.fixture(scope="session", autouse=True)
def _isolate_last_target(tmp_path_factory):
    """Redirect the global last-target file into a tmp dir so tests never clobber the user's real one.

    Per-PUT preferences are isolated by :func:`_bind_test_prefs`, but the last-target file
    lives in the user config dir (outside any PUT), so it needs its own guard — e.g. the
    Configuration-tab browse/commit flow calls :func:`write_last_target`, which would otherwise
    overwrite the real file with a tmp path.  Patching ``_last_target_file`` covers both
    :func:`read_last_target` and :func:`write_last_target`, which resolve it at call time.
    """
    import pytest_fly.paths as paths

    target_file = tmp_path_factory.mktemp("pytest_fly_test_config") / "last_target.txt"
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(paths, "_last_target_file", lambda: target_file)
    yield
    monkeypatch.undo()


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
