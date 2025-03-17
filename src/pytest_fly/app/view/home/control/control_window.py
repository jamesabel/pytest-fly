from typing import Callable

from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QSizePolicy
from PySide6.QtCore import QThread

from ....controller.pytest_runner import PytestRunnerWorker
from .....common import PytestProcessState, PytestProcessInfo, get_guid, RunParameters
from ....preferences import get_pref, ParallelismControl, RunMode
from .... import get_logger

from .control_pushbutton import ControlButton
from .parallelism_control_box import ParallelismControlBox
from .run_mode_control_box import RunModeControlBox

log = get_logger()


class ControlWindow(QGroupBox):

    def __init__(self, parent, reset_callback: Callable, update_callback: Callable[[PytestProcessInfo], None]):
        super().__init__(parent)
        self.reset_callback = reset_callback
        self.update_callback = update_callback
        self.setTitle("Control")

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.run_button = ControlButton(self, "Run", True)
        layout.addWidget(self.run_button)
        self.stop_button = ControlButton(self, "Stop", False)
        layout.addWidget(self.stop_button)
        layout.addStretch()

        self.parallelism_box = ParallelismControlBox(self)
        layout.addWidget(self.parallelism_box)

        self.run_mode_box = RunModeControlBox(self)
        layout.addWidget(self.run_mode_box)

        self.run_button.clicked.connect(self.run)
        self.stop_button.clicked.connect(self.stop)

        self.run_guid = None
        self.pytest_runner_thread = None
        self.pytest_runner_worker = None
        self.most_recent_statuses = {}

        self.pytest_runner_thread = QThread(self)  # work will be done in this thread
        # I'd like the thread to have some name, so use the name of the worker it'll be moved to
        self.pytest_runner_thread.setObjectName(PytestRunnerWorker.__class__.__name__)
        self.pytest_runner_worker = PytestRunnerWorker()
        self.pytest_runner_worker.moveToThread(self.pytest_runner_thread)  # move worker to thread
        self.pytest_runner_worker.request_exit_signal.connect(self.pytest_runner_thread.quit)  # required to stop the thread
        self.pytest_runner_worker.update_signal.connect(self.pytest_update)
        self.pytest_runner_thread.start()

        self.update_processes_configuration()

        # Calculate and set the fixed width
        self.set_fixed_width()

    def set_fixed_width(self):
        # Calculate the maximum width required by the child widgets
        max_width = max(self.run_button.sizeHint().width(), self.stop_button.sizeHint().width(), self.parallelism_box.sizeHint().width())
        # Add some padding
        max_width += 30
        self.setFixedWidth(max_width)

    def run(self):
        pref = get_pref()
        if pref.run_mode == RunMode.RESTART:
            self.reset_callback()
        self.run_guid = get_guid()
        run_parameters = RunParameters(self.run_guid, pref.run_mode, pref.processes)
        if pref.parallelism == ParallelismControl.SERIAL:
            run_parameters.max_processes = 1
        self.pytest_runner_worker.request_run(run_parameters)

    def stop(self):
        self.pytest_runner_worker.request_stop()
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def pytest_update(self, status: PytestProcessInfo):
        log.info(f"{status.name=}, {status.state=}, {status.exit_code=}")
        self.most_recent_statuses[status.name] = status
        self.update_callback(status)
        all_pytest_processes_finished = all([status.state == PytestProcessState.FINISHED for status in self.most_recent_statuses.values()])
        if all_pytest_processes_finished:
            self.run_button.setEnabled(True)
            self.stop_button.setEnabled(False)
        else:
            self.run_button.setEnabled(False)
            self.stop_button.setEnabled(True)
        self.update_processes_configuration()

    def update_processes_configuration(self):
        self.parallelism_box.update_preferences()
