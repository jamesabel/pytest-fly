from PySide6.QtWidgets import QWidget, QHBoxLayout, QSplitter, QScrollArea

from .control import ControlWindow
from .progress_window import ProgressWindow
from .summary_window import SummaryWindow
from pytest_fly.common.classes import PytestStatus
from ...logging import get_logger

log = get_logger()


class Home(QWidget):
    def __init__(self, parent, reset_callback, update_callback):
        super().__init__(parent)
        self.reset_callback = reset_callback
        self.update_callback = update_callback

        layout = QHBoxLayout()
        self.splitter = QSplitter()

        self.summary_window = SummaryWindow()
        self.progress_window = ProgressWindow()
        self.control_window = ControlWindow(self, self.reset, self.update_status)

        # Create scroll areas for both windows
        self.summary_scroll_area = QScrollArea()
        self.summary_scroll_area.setWidgetResizable(True)
        self.summary_scroll_area.setWidget(self.summary_window)

        self.progress_scroll_area = QScrollArea()
        self.progress_scroll_area.setWidgetResizable(True)
        self.progress_scroll_area.setWidget(self.progress_window)

        self.control_scroll_area = QScrollArea()
        self.control_scroll_area.setWidgetResizable(True)
        self.control_scroll_area.setWidget(self.control_window)

        self.splitter.addWidget(self.progress_scroll_area)
        self.splitter.addWidget(self.summary_scroll_area)
        self.splitter.addWidget(self.control_scroll_area)

        layout.addWidget(self.splitter)

        self.setLayout(layout)

        self.set_splitter()

    def reset(self):
        self.progress_window.reset()
        self.reset_callback()

    def update_status(self, status: PytestStatus):
        self.progress_window.update_status(status)
        self.summary_window.update_summary(status)
        self.set_splitter()
        self.update_callback(status)

    def set_splitter(self):
        log.info(f"{self.parent().size()=}")
        padding = 20
        overall_width = self.parent().size().width()
        summary_width = self.summary_window.size().width() + padding
        control_width = self.control_window.size().width() + padding
        progress_width = max(overall_width - summary_width - control_width, padding)
        log.info(f"{overall_width=},{progress_width=},{summary_width=},{control_width=}")
        self.splitter.setSizes([progress_width, summary_width, control_width])
