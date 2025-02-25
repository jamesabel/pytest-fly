from typing import Callable

from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QPushButton, QSizePolicy, QLabel
from PySide6.QtCore import QThread, QTimer


from ...controller.pytest_runner import PytestRunnerWorker
from ...model import PytestProcessState, PytestStatus
from ...preferences import get_pref
from ..gui_util import get_text_dimensions
from ... import get_logger

log = get_logger()


class ControlButton(QPushButton):

    def __init__(self, parent, text: str, enabled: bool):
        super().__init__(parent)
        self.setText(text)
        self.setEnabled(enabled)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.adjustSize()


class ControlWindow(QGroupBox):

    def __init__(self, parent, reset_callback: Callable, update_callback: Callable[[PytestStatus], None]):
        super().__init__(parent)
        self.reset_callback = reset_callback
        self.update_callback = update_callback
        self.setTitle("Control")

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.run_serial_button = ControlButton(self, "Run\nSerial", True)
        layout.addWidget(self.run_serial_button)
        self.run_parallel_button = ControlButton(self, "Run\nParallel", True)
        layout.addWidget(self.run_parallel_button)
        self.stop_button = ControlButton(self, "Stop", False)
        layout.addWidget(self.stop_button)
        layout.addStretch()
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedWidth(self.run_parallel_button.size().width() + 30)
        self.processes_label = QLabel()
        layout.addWidget(self.processes_label)

        self.run_serial_button.clicked.connect(self.run_serial)
        self.run_parallel_button.clicked.connect(self.run_multiprocess)
        self.stop_button.clicked.connect(self.stop)
        self.pytest_runner_thread = None
        self.pytest_runner_worker = None
        self.update_timer = QTimer()
        self.most_recent_statuses = {}

        self.pytest_runner_thread = QThread(self)  # work will be done in this thread
        # I'd like the thread to have some name, so use the name of the worker it'll be moved to
        self.pytest_runner_thread.setObjectName(PytestRunnerWorker.__class__.__name__)
        self.pytest_runner_worker = PytestRunnerWorker()
        self.pytest_runner_worker.moveToThread(self.pytest_runner_thread)  # move worker to thread
        self.pytest_runner_worker.request_exit_signal.connect(self.pytest_runner_thread.quit)  # required to stop the thread
        self.pytest_runner_worker.update_signal.connect(self.pytest_update)
        self.update_timer.timeout.connect(self.pytest_runner_worker.request_update)
        self.pytest_runner_thread.start()
        scheduler_time_quantum = get_pref().scheduler_time_quantum
        self.update_timer.start(int(round(scheduler_time_quantum * 1000.0)))  # convert to milliseconds

        self.update_processes_configuration()

    def run_serial(self):
        self.reset_callback()
        self.pytest_runner_worker.request_run(1)

    def run_multiprocess(self):
        self.reset_callback()
        max_number_of_processes = get_pref().processes
        self.pytest_runner_worker.request_run(max_number_of_processes)

    def stop(self):
        log.info(f"{__class__.__name__}.stop() - entering")
        self.pytest_runner_worker.request_stop()
        self.run_serial_button.setEnabled(True)
        self.run_parallel_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        log.info(f"{__class__.__name__}.stop() - exiting")

    def pytest_update(self, status: PytestStatus):
        log.info(f"{__class__.__name__}.pytest_update() - {status.name=}, {status.state=}, {status.exit_code=}")
        self.most_recent_statuses[status.name] = status
        log.info(f"{__class__.__name__}.pytest_update() - calling self.update_callback()")
        self.update_callback(status)
        log.info(f"{__class__.__name__}.pytest_update() - self.update_callback() returned")
        all_pytest_processes_finished = all([status.state == PytestProcessState.FINISHED for status in self.most_recent_statuses.values()])
        if all_pytest_processes_finished:
            self.run_serial_button.setEnabled(True)
            self.run_parallel_button.setEnabled(True)
            self.stop_button.setEnabled(False)
        else:
            self.run_serial_button.setEnabled(False)
            self.run_parallel_button.setEnabled(False)
            self.stop_button.setEnabled(True)
        self.update_processes_configuration()
        log.info(f"{__class__.__name__}.pytest_update() - exiting")

    def update_processes_configuration(self):
        processes = get_pref().processes
        text = f"{processes} processes"
        text_dimensions = get_text_dimensions(text, True)
        self.processes_label.setFixedWidth(text_dimensions.width())
        self.processes_label.setText(text)
