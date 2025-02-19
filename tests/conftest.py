import pytest
from PySide6.QtWidgets import QApplication

# required for local testing, even though these are "not used"
from pytest_fly import pytest_addoption, pytest_runtest_logreport, pytest_sessionfinish, pytest_sessionstart

pytest_plugins = "pytester"


@pytest.fixture(scope="session")
def app():
    return QApplication([])
