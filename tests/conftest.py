from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from pytest_fly import drop_pytest_process_current_info

pytest_plugins = "pytester"


@pytest.fixture(scope="session")
def app():
    return QApplication([])


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


@pytest.fixture(scope="function")
def init_pytest_process_info():
    drop_pytest_process_current_info()
    pass
