from pathlib import Path

from PySide6.QtWidgets import QWidget, QHBoxLayout
from typeguard import typechecked

from .control_window import ControlWindow
from .status_window import StatusWindow
from ...interfaces import PytestProcessInfo
from ...logger import get_logger

log = get_logger()


class RunTab(QWidget):

    @typechecked
    def __init__(self, parent, data_dir: Path):
        super().__init__(parent)

        layout = QHBoxLayout()
        self.setLayout(layout)

        self.control_window = ControlWindow(self, data_dir)
        self.status_window = StatusWindow(self)

        layout.addWidget(self.control_window)
        layout.addWidget(self.status_window)
        layout.addStretch()

    def update_pytest_process_info(self, pytest_process_infos: list[PytestProcessInfo]):
        self.status_window.update_status(pytest_process_infos)
