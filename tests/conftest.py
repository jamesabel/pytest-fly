from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from pytest_fly.preferences import init_preferences_for_put

pytest_plugins = "pytester"


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
