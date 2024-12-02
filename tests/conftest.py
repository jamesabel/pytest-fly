from multiprocessing import Process
import time

# required for local testing, even though these are "not used"
from src.pytest_fly import pytest_addoption, pytest_runtest_logreport, pytest_sessionfinish, pytest_sessionstart

import pytest
from src.pytest_fly.visualization import visualize
from src.pytest_fly.xdist_workers import is_main_worker
from src.pytest_fly.db import PytestFlyDB

from tests.orchestrator import TstOrchestrator, init_port, remove_port

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

        init_port()

        # pop up one app/window in a separate process
        # visualize_process = VisualizeProcess()
        # visualize_process.start()

        orchestrator = TstOrchestrator()  # tells tests what to do (when running in parallel using xdist)
        orchestrator.start()

        yield True

        # visualize_process.terminate()
        orchestrator.terminate()
        remove_port()
    else:
        yield True
