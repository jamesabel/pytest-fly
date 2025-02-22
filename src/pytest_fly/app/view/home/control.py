from typing import Callable

from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QPushButton
from PySide6.QtCore import QThread, QTimer


from ...controller.pytest_runner import PytestRunnerWorker
from ...model import PytestProcessState, PytestStatus
from ... import get_logger

log = get_logger()


class ControlWindow(QGroupBox):

    def __init__(self, parent, update_callback: Callable[[PytestStatus], None]):
        super().__init__(parent)
        self.update_callback = update_callback
        self.setTitle("Control")
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.run_button = QPushButton("Run")
        layout.addWidget(self.run_button)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        layout.addWidget(self.stop_button)
        layout.addStretch()
        self.run_button.clicked.connect(self.run)
        self.stop_button.clicked.connect(self.stop)
        self.pytest_runner_thread = None
        self.pytest_runner_worker = None
        self.update_timer = QTimer()
        self.statuses = {}

        self.pytest_runner_thread = QThread(self)  # work will be done in this thread
        # I'd like the thread to have some name, so use the name of the worker it'll be moved to
        self.pytest_runner_thread.setObjectName(PytestRunnerWorker.__class__.__name__)
        self.pytest_runner_worker = PytestRunnerWorker()
        self.pytest_runner_worker.moveToThread(self.pytest_runner_thread)  # move worker to thread
        self.pytest_runner_worker.request_exit_signal.connect(self.pytest_runner_thread.quit)  # required to stop the thread
        self.pytest_runner_worker.update_signal.connect(self.pytest_update)
        self.update_timer.timeout.connect(self.pytest_runner_worker.request_update)
        self.pytest_runner_thread.start()
        self.update_timer.start(1000)

    def run(self):
        self.pytest_runner_worker.request_run()

    def stop(self):
        log.info(f"{__class__.__name__}.stop() - entering")
        self.pytest_runner_worker.request_stop()
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        log.info(f"{__class__.__name__}.stop() - exiting")

    def pytest_update(self, status: PytestStatus):
        log.info(f"{__class__.__name__}.pytest_update() - {status.name=}, {status.state=}, {status.exit_code=}")
        self.statuses[status.name] = status
        log.info(f"{__class__.__name__}.pytest_update() - calling self.update_callback()")
        self.update_callback(status)
        log.info(f"{__class__.__name__}.pytest_update() - self.update_callback() returned")
        all_pytest_processes_finished = all([status.state == PytestProcessState.FINISHED for status in self.statuses.values()])
        if all_pytest_processes_finished:
            self.run_button.setEnabled(True)
            self.stop_button.setEnabled(False)
        else:
            self.run_button.setEnabled(False)
            self.stop_button.setEnabled(True)
        log.info(f"{__class__.__name__}.pytest_update() - exiting")
