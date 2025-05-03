from pathlib import Path
import time

from PySide6.QtCore import QThread
from pytest import ExitCode
from pytest_fly.app.controller import PytestRunnerWorker
from pytest_fly.app.model import PytestProcessState, get_performance_core_count, get_guid, RunParameters, RunMode


def test_pytest_runner(app):
    statuses = []

    def append_to_worker_statuses(_status):
        # print(_status)
        statuses.append(_status)

    # run twice to test the worker's ability to run multiple tests
    for run_count in range(2):
        test = ["tests", "test_sleep.py"]
        test_path = Path(*test)  # an "easy" test
        worker = PytestRunnerWorker([str(test_path)])
        thread = QThread()
        worker.moveToThread(thread)

        # connect worker and thread
        worker.request_exit_signal.connect(thread.quit)
        worker.update_signal.connect(append_to_worker_statuses)
        thread.start()

        performance_core_count = get_performance_core_count()
        run_guid = get_guid()
        run_parameters = RunParameters(run_guid, RunMode.RESTART, performance_core_count)
        worker.request_run(run_parameters)
        app.processEvents()

        # the statuses list will be updated in the background in the worker thread
        count = 0
        finished = False
        statuses.clear()
        while not finished and count < 100:
            app.processEvents()

            # determine if the test has finished
            for status in statuses:
                if status.state == PytestProcessState.FINISHED:
                    finished = True
            if not finished:
                time.sleep(1)

            count += 1

        if len(statuses) >= 3:
            # resume (doesn't have to run)
            assert statuses[0].exit_code is None
            assert statuses[0].state == PytestProcessState.QUEUED
            assert statuses[1].exit_code is None
            assert statuses[1].state == PytestProcessState.RUNNING
        assert len(statuses) >= 1
        assert statuses[-1].exit_code == ExitCode.OK
        assert statuses[-1].state == PytestProcessState.FINISHED

        worker.request_exit()
        app.processEvents()

        # ensure worker exits properly
        count = 0
        while thread.isRunning() and count < 10:
            # app.processEvents()
            thread.wait(10 * 1000)
            count += 1
