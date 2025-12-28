from pathlib import Path
from queue import Queue, Empty
from typing import Optional
from threading import Event
from collections import defaultdict

from PySide6.QtCore import QObject, Signal, Slot, QThread
from typeguard import typechecked

from ..logger import get_logger
from ..interfaces import ScheduledTests
from ..guid import generate_uuid
from ..__version__ import application_name
from .pytest_process import PytestProcess
from .const import TIMEOUT

log = get_logger()


class PytestRunner(QThread):
    def __init__(self, tests: ScheduledTests, number_of_processes: int, coverage_parent_directory: Path, update_rate: float):
        super().__init__()

        self.setObjectName(application_name)

        self.tests = tests
        self.number_of_processes = number_of_processes
        self.coverage_parent_directory = coverage_parent_directory
        self.update_rate = update_rate

        # parallel dictionaries of threads and workers (index is thread number)
        self._pytest_runner_threads = {}
        self._pytest_runner_workers = {}
        self._results = defaultdict(list)

    def run(self):

        test_queue = Queue()
        for test in self.tests:
            test_queue.put(test.node_id)

        run_guid = generate_uuid()

        for thread_number in range(self.number_of_processes):
            pytest_runner_thread = QThread()  # work will be done in this thread
            pytest_runner_thread.setObjectName(f"{application_name}_thread_{thread_number}")
            pytest_runner_worker = _PytestRunnerWorker(pytest_runner_thread, run_guid, test_queue, self.coverage_parent_directory, self.update_rate)
            pytest_runner_worker.moveToThread(pytest_runner_thread)  # move worker to thread
            pytest_runner_thread.started.connect(pytest_runner_worker.run)  # when thread starts, run the worker
            pytest_runner_thread.finished.connect(pytest_runner_worker.deleteLater)
            pytest_runner_thread.finished.connect(pytest_runner_thread.deleteLater)
            pytest_runner_thread.start()
            self._pytest_runner_threads[thread_number] = pytest_runner_thread
            self._pytest_runner_workers[thread_number] = pytest_runner_worker

    def is_running(self) -> bool:
        any_running = any(t.isRunning() for t in self._pytest_runner_threads.values())
        return any_running

    def join(self, seconds: float | None = None) -> bool:
        if seconds is None:
            milliseconds = None
        else:
            milliseconds = int(1000.0 * seconds)
        finished = []
        for pytest_runner_thread in self._pytest_runner_threads.values():
            finished.append(pytest_runner_thread.wait(milliseconds))
        return all(finished)

    def stop(self):
        for worker_number, pytest_runner_worker in self._pytest_runner_workers.items():
            if pytest_runner_worker.is_running():
                pytest_runner_worker.stop()

    def get_results(self) -> dict[int, list]:
        for worker_number, worker in self._pytest_runner_workers.items():
            if (process := worker.process) is not None:
                while True:
                    try:
                        result = process.pytest_monitor_queue.get(block=False)
                        self._results[worker_number].append(result)
                    except Empty:
                        break
        return dict(self._results)


class _PytestRunnerWorker(QObject):
    """
    Worker that runs pytest tests in separate processes.
    """

    _run_signal = Signal()
    _stop_signal = Signal()

    @typechecked()
    def __init__(self, parent_thread: QThread, run_guid: str, pytest_work_queue: Queue, coverage_parent_directory: Path, update_rate: float) -> None:
        """
        Pytest runner worker.
        """
        super().__init__()

        self.parent_thread = parent_thread
        self.run_guid = run_guid
        self.pytest_work_queue = pytest_work_queue
        self.coverage_parent_directory = coverage_parent_directory
        self.update_rate = update_rate  # for the process monitor

        self.process: Optional[PytestProcess] | None = None
        self._stop_event = Event()

        self._run_signal.connect(self._run)
        self._stop_signal.connect(self._stop)

    def stop(self):
        self._stop_signal.emit()

    def run(self):
        self._run_signal.emit()

    def is_running(self) -> bool:
        return not self._stop_event.is_set()

    @Slot()
    def _run(self):
        while not self._stop_event.is_set():
            try:
                test = self.pytest_work_queue.get(False)
                self.process = PytestProcess(self.run_guid, test, self.coverage_parent_directory, self.update_rate)
                log.info(f'Starting process for test "{test}" ({self.run_guid=})')
                self.process.start()
            except Empty:
                self.stop()  # no more work to do
                break

            while self.process.is_alive():
                if self._stop_event.is_set():
                    self.process.terminate()  # force current test to stop
                self.process.join(self.update_rate)
            self.process.join(TIMEOUT)  # should already be done, but just in case
            if self.process.is_alive():
                log.warning(f'process for test "{self.process.name}" did not terminate')
            else:
                log.info(f'process for test "{self.process.name}" completed ({self.run_guid=})')

    @Slot()
    def _stop(self):
        if self.process is not None and self.process.is_alive():
            self.process.terminate()  # force current test to stop
            self.process.join(TIMEOUT)
        self._stop_event.set()
        self.parent_thread.exit()  # no more work to do
