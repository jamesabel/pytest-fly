from pathlib import Path
from threading import Event
from typing import Callable
import time

from PySide6.QtCore import Signal, QThread
from PySide6.QtWidgets import QMainWindow, QApplication, QWidget, QHBoxLayout, QSplitter, QScrollArea
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from ...__version__ import application_name
from ...db import get_db_path, get_most_recent_run_info, fly_db_file_name
from ..csv_dump import csv_dump
from ..preferences import get_pref
from .bar_chart_window import BarChartWindow
from .status_window import StatusWindow


class DatabaseChangeHandler(FileSystemEventHandler):
    def __init__(self, update_callback):
        self.update_callback = update_callback
        super().__init__()

    def on_modified(self, event):
        if Path(event.src_path).name == fly_db_file_name:
            self.update_callback()


class CentralWindow(QWidget):
    def __init__(self):
        super().__init__()

        layout = QHBoxLayout()
        self.splitter = QSplitter()

        self.status_window = StatusWindow()
        self.bar_chart_window = BarChartWindow()

        # Create scroll areas for both windows
        self.status_scroll_area = QScrollArea()
        self.status_scroll_area.setWidgetResizable(True)
        self.status_scroll_area.setWidget(self.status_window)

        self.bar_chart_scroll_area = QScrollArea()
        self.bar_chart_scroll_area.setWidgetResizable(True)
        self.bar_chart_scroll_area.setWidget(self.bar_chart_window)

        self.splitter.addWidget(self.bar_chart_scroll_area)
        self.splitter.addWidget(self.status_scroll_area)

        layout.addWidget(self.splitter)

        self.setLayout(layout)

    def set_sizes(self, sizes: list[int]):
        self.splitter.setSizes(sizes)

    def get_sizes(self) -> list[int]:
        return self.splitter.sizes()

    def update_window(self, run_infos: dict):
        self.status_window.update_window(run_infos)
        self.bar_chart_window.update_window(run_infos)


class PeriodicUpdater(QThread):
    _wait_time_signal = Signal(float)

    def __init__(self, update_callback: Callable):
        super().__init__()
        self._wait_time = 1.0  # seconds
        self.update_callback = update_callback
        self._stop_event = Event()
        self._wait_time_signal.connect(self._set_wait_time)

    def run(self):
        while not self._stop_event.is_set():
            self.update_callback()
            self._stop_event.wait(self._wait_time)

    def request_stop(self):
        self._stop_event.set()

    def _set_wait_time(self, wait_time: float):
        self._wait_time = wait_time

    def request_new_wait_time(self, new_wait_time: float):
        self._wait_time_signal.emit(new_wait_time)

    def get_wait_time(self) -> float:
        return self._wait_time


class VisualizationQt(QMainWindow):
    _update_signal = Signal()

    def __init__(self):
        super().__init__()

        self.setWindowTitle(application_name)

        self.central_window = CentralWindow()

        # restore window position and size
        pref = get_pref()
        screen = QApplication.primaryScreen()
        available_geometry = screen.availableGeometry()
        x = min(pref.window_x, available_geometry.width() - 1)
        y = min(pref.window_y, available_geometry.height() - 1)
        width = min(pref.window_width, available_geometry.width())
        height = min(pref.window_height, available_geometry.height())
        splitter_left = pref.splitter_left
        splitter_right = pref.splitter_right
        if x > 0 and y > 0 and width > 0 and height > 0 and splitter_left > 0 and splitter_right > 0:
            self.setGeometry(x, y, width, height)
            self.central_window.set_sizes([splitter_left, splitter_right])

        self.setCentralWidget(self.central_window)

        # start file watcher
        self.event_handler = DatabaseChangeHandler(self.request_update)
        self.observer = Observer()
        db_path = get_db_path()
        self.observer.schedule(self.event_handler, path=str(db_path.parent), recursive=False)  # watchdog watches a directory
        self.observer.start()
        self._update_signal.connect(self.update_plot)

        self.periodic_updater = PeriodicUpdater(self.request_update)
        self.periodic_updater.start()
        self.request_update()

    def request_update(self):
        self._update_signal.emit()

    def update_plot(self):
        start = time.time()
        pref = get_pref()
        run_infos = get_most_recent_run_info()
        self.central_window.update_window(run_infos)
        csv_dump(run_infos, Path(pref.csv_dump_path))
        duration = time.time() - start
        update_overhead = 0.1
        new_wait_time = max(1.0, duration / update_overhead)
        self.periodic_updater.request_new_wait_time(new_wait_time)
        wait_time = self.periodic_updater.get_wait_time()
        self.setWindowTitle(f"{application_name} (update time: {wait_time:.1f}s)")

    def closeEvent(self, event):
        pref = get_pref()

        pref.window_x = self.x()
        frame_height = self.frameGeometry().height() - self.geometry().height()
        pref.window_y = self.y() + frame_height
        pref.window_width = self.width()
        pref.window_height = self.height()

        sizes = self.central_window.get_sizes()
        pref.splitter_left = sizes[0]
        pref.splitter_right = sizes[1]

        self.observer.stop()
        self.periodic_updater.request_stop()
        self.observer.join()
        self.periodic_updater.wait()

        event.accept()


def visualize_qt():
    app = QApplication([])
    viz_qt = VisualizationQt()
    viz_qt.show()
    app.exec()
