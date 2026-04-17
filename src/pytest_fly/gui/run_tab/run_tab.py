"""Run tab — combines the control panel (Run/Stop buttons) with the status summary."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from typeguard import typechecked

from ...logger import get_logger
from ...tick_data import TickData
from .control_window import ControlWindow
from .failed_tests_window import FailedTestsWindow
from .status_window import StatusWindow

log = get_logger()


class RunTab(QWidget):
    """Primary tab combining the control panel (Run/Stop) and the status summary."""

    @typechecked
    def __init__(self, parent, data_dir: Path):
        super().__init__(parent)

        outer_layout = QVBoxLayout()
        self.setLayout(outer_layout)

        top_layout = QHBoxLayout()
        top_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.control_window = ControlWindow(self, data_dir)
        self.status_window = StatusWindow(self)
        self.failed_tests_window = FailedTestsWindow(self)

        # Match StatusWindow's height to ControlWindow's so the two panels line up.
        # ControlWindow has Fixed size policy (set in its __init__), so its sizeHint is stable.
        self.status_window.setFixedHeight(self.control_window.sizeHint().height())

        top_layout.addWidget(self.control_window, alignment=Qt.AlignmentFlag.AlignTop)
        top_layout.addWidget(self.status_window, alignment=Qt.AlignmentFlag.AlignTop)
        top_layout.addStretch()

        outer_layout.addLayout(top_layout)
        outer_layout.addWidget(self.failed_tests_window, stretch=1)

    def update_tick(self, tick: TickData):
        """Forward pre-computed tick data to the status window, failed tests pane, and control panel."""
        self.status_window.update_tick(tick)
        self.failed_tests_window.update_tick(tick)
        self.control_window.update()
