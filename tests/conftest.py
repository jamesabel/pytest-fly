# required for local testing, even though these are "not used"
from src.pytest_fly import pytest_addoption, pytest_runtest_logreport, pytest_sessionfinish, pytest_sessionstart


pytest_plugins = "pytester"
