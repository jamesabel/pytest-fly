from PySide6.QtWidgets import QWidget, QHBoxLayout, QSplitter, QScrollArea

from .control import ControlWindow
from .progress_window import ProgressWindow
from .status_window import StatusWindow
from ...model import PytestStatus


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

        self.plot_scroll_area = QScrollArea()
        self.plot_scroll_area.setWidgetResizable(True)
        self.plot_scroll_area.setWidget(self.progress_window)

        self.control_scroll_area = QScrollArea()
        self.control_scroll_area.setWidgetResizable(True)
        self.control_scroll_area.setWidget(self.control_window)

        self.splitter.addWidget(self.plot_scroll_area)
        self.splitter.addWidget(self.status_scroll_area)
        self.splitter.addWidget(self.control_scroll_area)

        layout.addWidget(self.splitter)

        self.setLayout(layout)

    def update_status(self, status: PytestStatus):
        self.status_window.update_status(status)
        self.progress_window.update_status(status)
