from pprint import pprint
from pathlib import Path

from PySide6.QtCore import QThread
from pytest import ExitCode
from pytest_fly.app.controller import PytestRunnerWorker


def test_pytest_runner(app):

    # run twice to test the worker's ability to run multiple tests
    for _ in range(2):
        tests = [Path("tests", "test_sleep.py")]  # an "easy" test
        worker = PytestRunnerWorker(tests)  # append updates the results list
        thread = QThread()
        worker.moveToThread(thread)

        statuses = []

        # connect worker and thread
        thread.started.connect(worker.run)
        worker.update.connect(lambda status: statuses.append(status))
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)

        thread.start()

        while thread.isRunning():
            app.processEvents()  # allows the QThread to finish

        assert len(statuses) == 2
        assert statuses[0].exit_code is None
        assert statuses[1].exit_code == ExitCode.OK
