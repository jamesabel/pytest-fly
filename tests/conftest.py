from multiprocessing import Process
import time

# required for local testing, even though these are "not used"
from src.pytest_fly import pytest_addoption, pytest_runtest_logreport, pytest_sessionfinish

import pytest
from src.pytest_fly.visualization import visualize
from src.pytest_fly.xdist_workers import is_main_worker
from src.pytest_fly.db import PytestFlyDB

from tests.orchestrator import Orchestrator, init_port, remove_port

pytest_plugins = "pytester"


class RunVisualize(Process):
    def __init__(self):
        super().__init__()
        self.daemon = True

    def run(self):
        visualize()


@pytest.fixture(scope="session", autouse=True)
def run_visualize() -> bool:
    """
    Run pytest-fly visualization.
    """
    if is_main_worker():

        init_port()

        db = PytestFlyDB("test")
        db.delete()  # start from scratch

        orchestrator = Orchestrator()  # tells tests what to do (when running in parallel using xdist)
        orchestrator.start()

        # pop up one app/window in a separate process
        run_visualize = RunVisualize()
        run_visualize.start()
        yield True
        time.sleep(10)
        run_visualize.terminate()
        orchestrator.terminate()
        remove_port()
    else:
        yield False
