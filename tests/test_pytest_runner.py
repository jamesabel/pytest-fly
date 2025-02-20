from pathlib import Path
import time

from PySide6.QtCore import QThread
from pytest import ExitCode
from pytest_fly.app.controller import PytestRunnerWorker


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
        thread.started.connect(worker.run)
        worker.update_signal.connect(statuses.append)
        thread.start()

        worker.request_run()

        count = 0
        while len(statuses) != 2 and count < 100:
            app.processEvents()  # allows the pytest runner to finish
            time.sleep(1)
            count += 1

        assert len(statuses) == 2
        assert statuses[0].exit_code is None
        assert statuses[1].exit_code == ExitCode.OK

        worker.request_exit_signal.emit()
        count = 0
        while thread.isRunning() and count < 10:
            app.processEvents()
            thread.wait(10 * 1000)
            count += 1
