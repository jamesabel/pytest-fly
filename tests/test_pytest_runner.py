from pathlib import Path
import time

from PySide6.QtCore import QThread
from pytest import ExitCode
from pytest_fly.app.controller import PytestRunnerWorker
from pytest_fly.app.model import PytestProcessState


def test_pytest_runner(app):

    # run twice to test the worker's ability to run multiple tests
    for run_count in range(2):
        tests = [Path("tests", "test_sleep.py")]  # an "easy" test
        worker = PytestRunnerWorker(tests)
        thread = QThread()
        worker.moveToThread(thread)

        statuses = []

        # connect worker and thread
        worker.request_exit_signal.connect(thread.quit)
        worker.update_signal.connect(statuses.append)
        thread.start()

        worker._request_run_signal.emit()
        app.processEvents()

        # the statuses list will be updated in the background in the worker thread
        count = 0
        while len(statuses) != 3 and count < 100:
            worker._request_update_signal.emit()
            app.processEvents()
            time.sleep(1)
            count += 1

        assert len(statuses) == 3  # QUEUED, RUNNING, FINISHED
        assert statuses[0].exit_code is None
        assert statuses[0].state == PytestProcessState.QUEUED
        assert statuses[1].exit_code is None
        assert statuses[1].state == PytestProcessState.RUNNING
        assert statuses[2].exit_code == ExitCode.OK
        assert statuses[2].state == PytestProcessState.FINISHED

        # tell worker to stop and exit
        worker.request_stop()
        app.processEvents()
        worker.request_exit()
        app.processEvents()

        # ensure worker exits properly
        count = 0
        while thread.isRunning() and count < 10:
            app.processEvents()
            thread.wait(10 * 1000)
            count += 1
