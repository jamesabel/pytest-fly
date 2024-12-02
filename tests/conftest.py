from multiprocessing import Process

# required for local testing, even though these are "not used"
from src.pytest_fly import pytest_addoption, pytest_runtest_logreport, pytest_sessionfinish, pytest_sessionstart

import pytest
from src.pytest_fly.visualization import visualize
from src.pytest_fly.xdist_workers import is_main_worker


pytest_plugins = "pytester"


class VisualizeProcess(Process):
    def run(self):
        visualize()


@pytest.fixture(scope="session", autouse=True)
def run_visualize():
    """
    Run pytest-fly visualization.
    """
    if is_main_worker():

        # pop up one app/window in a separate process
        visualize_process = VisualizeProcess()
        visualize_process.start()

        yield True

        visualize_process.terminate()

    else:
        yield True
