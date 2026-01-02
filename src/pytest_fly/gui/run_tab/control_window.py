from pathlib import Path

from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QSizePolicy
from PySide6.QtCore import Qt
from typeguard import typechecked

from ...interfaces import RunParameters
from ...pytest_runner.pytest_runner import PytestRunner
from ...pytest_runner.test_list import get_tests
from ...preferences import get_pref, ParallelismControl
from ...logger import get_logger
from ...guid import generate_uuid

from .control_pushbutton import ControlButton
from .parallelism_control_box import ParallelismControlBox
from .run_mode_control_box import RunModeControlBox
from .view_coverage import ViewCoverage

log = get_logger()


class ControlWindow(QGroupBox):

    @typechecked()
    def __init__(self, parent, data_dir: Path):
        super().__init__(parent)
        self.data_dir = data_dir

        self.run_guid: str | None = None

        self.setTitle("Control")

        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setLayout(layout)

        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.run_button = ControlButton(self, "Run", True)
        layout.addWidget(self.run_button)
        self.run_button.clicked.connect(self.run)

        self.stop_button = ControlButton(self, "Stop", False)
        layout.addWidget(self.stop_button)
        self.stop_button.clicked.connect(self.stop)

        layout.addStretch()

        self.parallelism_box = ParallelismControlBox(self)
        layout.addWidget(self.parallelism_box)

        self.run_mode_box = RunModeControlBox(self)
        layout.addWidget(self.run_mode_box)

        self.view_coverage_button = ControlButton(self, "View Coverage", True)
        self.view_coverage = ViewCoverage(self.data_dir)
        self.view_coverage_button.clicked.connect(self.view_coverage.view)
        layout.addWidget(self.view_coverage_button)

        self.pytest_runner: PytestRunner | None = None

        self.set_fixed_width()  # calculate and set the widget width

    def set_fixed_width(self):
        # Calculate the maximum width required by the child widgets
        max_width = max(self.run_button.sizeHint().width(), self.stop_button.sizeHint().width(), self.parallelism_box.sizeHint().width())
        # Add some padding
        max_width += 30
        self.setFixedWidth(max_width)

    def update(self):
        if self.pytest_runner is None or not self.pytest_runner.is_running():
            self.run_button.setEnabled(True)
            self.stop_button.setEnabled(False)
        else:
            self.run_button.setEnabled(False)
            self.stop_button.setEnabled(True)

    def run(self):
        pref = get_pref()
        refresh_rate = pref.refresh_rate
        self.run_guid = generate_uuid()
        run_parameters = RunParameters(self.run_guid, pref.run_mode, pref.processes)
        if pref.parallelism == ParallelismControl.SERIAL:
            run_parameters.max_processes = 1

        tests = get_tests()
        if self.pytest_runner is not None and self.pytest_runner.is_running():
            self.pytest_runner.stop()
            self.pytest_runner.join()
        self.pytest_runner = PytestRunner(self.run_guid, tests, run_parameters.max_processes, self.data_dir, refresh_rate)
        self.pytest_runner.start()
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)

    def stop(self):
        self.pytest_runner.stop()
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.run_guid = None
