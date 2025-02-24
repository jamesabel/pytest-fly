from PySide6.QtWidgets import QWidget, QHBoxLayout, QSplitter, QScrollArea

from .control import ControlWindow
from .progress_window import ProgressWindow
from .status_window import StatusWindow
from ...model import PytestStatus
from ...logging import get_logger

log = get_logger()


class Home(QWidget):
    def __init__(self, parent):
        super().__init__(parent)

        layout = QHBoxLayout()
        self.splitter = QSplitter()

        self.status_window = StatusWindow()
        self.progress_window = ProgressWindow()
        self.control_window = ControlWindow(self, self.progress_window.reset, self.update_status)

        # Create scroll areas for both windows
        self.status_scroll_area = QScrollArea()
        self.status_scroll_area.setWidgetResizable(True)
        self.status_scroll_area.setWidget(self.status_window)

        self.progress_scroll_area = QScrollArea()
        self.progress_scroll_area.setWidgetResizable(True)
        self.progress_scroll_area.setWidget(self.progress_window)

        self.control_scroll_area = QScrollArea()
        self.control_scroll_area.setWidgetResizable(True)
        self.control_scroll_area.setWidget(self.control_window)

        self.splitter.addWidget(self.progress_scroll_area)
        self.splitter.addWidget(self.status_scroll_area)
        self.splitter.addWidget(self.control_scroll_area)

        layout.addWidget(self.splitter)

        self.setLayout(layout)

        self.set_splitter()

    def update_status(self, status: PytestStatus):
        self.status_window.update_status(status)
        self.progress_window.update_status(status)
        self.status_window.update_status(status)
        self.progress_window.update_status(status)
        self.set_splitter()

    def set_splitter(self):
        log.info(f"{self.parent().size()=}")
        padding = 20
        overall_width = self.parent().size().width()
        status_width = self.status_window.size().width() + padding
        control_width = self.control_window.size().width() + padding
        progress_width = max(overall_width - status_width - control_width, padding)
        log.info(f"{overall_width=},{progress_width=},{status_width=},{control_width=}")
        self.splitter.setSizes([progress_width, status_width, control_width])
