from pathlib import Path
from threading import Event
from typing import Callable

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QWidget, QHBoxLayout, QSplitter, QScrollArea
from watchdog.events import FileSystemEventHandler

from pytest_fly.db import fly_db_file_name
from .control import ControlWindow
from .progress_window import ProgressWindow
from .status_window import StatusWindow


class Home(QWidget):
    def __init__(self, parent):
        super().__init__(parent)

        layout = QHBoxLayout()
        self.splitter = QSplitter()

        self.status_window = StatusWindow()
        self.plot_window = ProgressWindow()
        self.control_window = ControlWindow(self, self.status_window.update_status)

        # Create scroll areas for both windows
        self.status_scroll_area = QScrollArea()
        self.status_scroll_area.setWidgetResizable(True)
        self.status_scroll_area.setWidget(self.status_window)

        self.plot_scroll_area = QScrollArea()
        self.plot_scroll_area.setWidgetResizable(True)
        self.plot_scroll_area.setWidget(self.plot_window)

        self.control_scroll_area = QScrollArea()
        self.control_scroll_area.setWidgetResizable(True)
        self.control_scroll_area.setWidget(self.control_window)

        self.splitter.addWidget(self.plot_scroll_area)
        self.splitter.addWidget(self.status_scroll_area)
        self.splitter.addWidget(self.control_scroll_area)

        layout.addWidget(self.splitter)

        self.setLayout(layout)


class DatabaseChangeHandler(FileSystemEventHandler):
    def __init__(self, update_callback):
        self.update_callback = update_callback
        super().__init__()

    def on_modified(self, event):
        if Path(event.src_path).name == fly_db_file_name:
            self.update_callback()


class PeriodicUpdater(QThread):
    def __init__(self, update_callback: Callable):
        super().__init__()
        self.update_callback = update_callback
        self._stop_event = Event()

    def run(self):
        while not self._stop_event.is_set():
            self.update_callback()
            self._stop_event.wait(1)

    def request_stop(self):
        self._stop_event.set()
