from pathlib import Path

from PySide6.QtWidgets import QWidget, QHBoxLayout, QSplitter, QScrollArea
from typeguard import typechecked

from .control_window import ControlWindow
from .summary_window import SummaryWindow
from ...interfaces import PytestProcessInfo
from ...logger import get_logger

log = get_logger()


class RunTab(QWidget):

    @typechecked
    def __init__(self, parent, data_dir: Path):
        super().__init__(parent)
        self.summary_window = SummaryWindow()

        layout = QHBoxLayout()
        self.splitter = QSplitter()

        self.control_window = ControlWindow(self, data_dir)

        # Create scroll areas for both windows
        self.summary_scroll_area = QScrollArea()
        self.summary_scroll_area.setWidgetResizable(True)
        self.summary_scroll_area.setWidget(self.summary_window)

        self.control_scroll_area = QScrollArea()
        self.control_scroll_area.setWidgetResizable(True)
        self.control_scroll_area.setWidget(self.control_window)

        self.splitter.addWidget(self.control_scroll_area)
        self.splitter.addWidget(self.summary_scroll_area)

        layout.addWidget(self.splitter)

        self.setLayout(layout)

    def update_pytest_process_info(self, pytest_process_infos: list[PytestProcessInfo]):
        self.summary_window.update_summary(pytest_process_infos)
