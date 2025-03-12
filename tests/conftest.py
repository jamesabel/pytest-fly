from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

# required for local testing, even though these are "not used"
from pytest_fly import pytest_addoption, pytest_runtest_logreport, pytest_sessionfinish, pytest_sessionstart

pytest_plugins = "pytester"


@pytest.fixture(scope="session")
def app():
    return QApplication([])


@pytest.fixture(scope="session", autouse=True)
def make_many_tests():
    """
    Makes many tests in order to test pytest_fly itself for things like scrollable windows and saving off Window dimensions that aren't off the screen.
    """
    test_parent_glob = list(Path().glob("test*"))
    assert len(test_parent_glob) == 1
    test_parent = test_parent_glob[0]
    many_test_dir = Path(test_parent, "tests_many")
    if not many_test_dir.exists():
        print(f'making "{many_test_dir}"')
        many_test_dir.mkdir(exist_ok=True, parents=True)
        # more than can fit in a window without scroll bars
        for test_number in range(20):
            test_file = Path(many_test_dir, f"test_many_{test_number:03d}.py")
            lines = [f"def test_many_{test_number}():", "    print(sum([x for x in range((int(1E7)))]))", "    assert True\n"]
            test_file.write_text("\n".join(lines))
