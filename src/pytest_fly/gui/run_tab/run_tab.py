from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QWidget
from typeguard import typechecked

from ...logger import get_logger
from ...tick_data import TickData
from .control_window import ControlWindow
from .status_window import StatusWindow

log = get_logger()


class RunTab(QWidget):
    """Primary tab combining the control panel (Run/Stop) and the status summary."""

    @typechecked
    def __init__(self, parent, data_dir: Path):
        super().__init__(parent)

        layout = QHBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setLayout(layout)

        self.control_window = ControlWindow(self, data_dir)
        self.status_window = StatusWindow(self)

        layout.addWidget(self.control_window, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.status_window, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addStretch()

    def update_tick(self, tick: TickData):
        """Forward pre-computed tick data to the status window and control panel."""
        self.status_window.update_tick(tick)
        self.control_window.update()
