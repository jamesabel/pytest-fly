from pathlib import Path
from datetime import datetime, timedelta
from typing import Callable
from threading import Event
from logging import getLogger
from copy import deepcopy

from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox
from PySide6.QtCore import QThread, Signal
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import numpy as np
import matplotlib.pyplot as plt

from ..db import get_most_recent_run_info, get_db_path, fly_db_file_name
from ..utilization import calculate_utilization
from ..__version__ import application_name
from .preferences import get_pref

log = getLogger(application_name)


def time_delta_to_string(td: timedelta) -> str:
    """
    Convert a timedelta to a string in the format "HH:MM:SS.NNN".
    """
    s = f"{td.seconds // 3600:02}:{(td.seconds // 60) % 60:02}:{td.seconds % 60:02}.{td.microseconds // 100000:1}"
    return s


class DatabaseChangeHandler(FileSystemEventHandler):
    def __init__(self, update_callback):
        self.update_callback = update_callback
        super().__init__()

    def on_modified(self, event):
        if Path(event.src_path).name == fly_db_file_name:
            self.update_callback()


class TestPlotCanvas(FigureCanvas):
    def __init__(self, parent=None, width=5, height=4, dpi=100):
        fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = fig.add_subplot(111)
        super().__init__(fig)
        self.setParent(parent)
        fig.subplots_adjust(left=0.25)  # Adjust the left margin

    def update_plot(self, run_info: dict):
        """
        Update the plot with the most recent data from the database.
        """

        if len(run_info) > 0:

            sorted_data = dict(sorted(run_info.items(), key=lambda x: x[0], reverse=True))
            worker_utilization, overall_utilization = calculate_utilization(sorted_data)
            if len(starts := [phase.start for test in sorted_data.values() for phase in test.values()]) > 0:
                earliest_start = min(starts)
            else:
                earliest_start = 0

            workers = set(info.worker_id for test in sorted_data.values() for info in test.values())
            colors = plt.cm.jet(np.linspace(0, 1, len(workers)))
            worker_colors = dict(zip(workers, colors))

            self.axes.clear()

            y_ticks, y_tick_labels = [], []
            for i, (test_name, phases) in enumerate(sorted_data.items()):
                for phase_name, phase_info in phases.items():
                    relative_start = phase_info.start - earliest_start
                    relative_stop = phase_info.stop - earliest_start
                    worker_id = phase_info.worker_id

                    self.axes.plot([relative_start, relative_stop], [i, i], color=worker_colors[worker_id], marker="o", markersize=4)

                    # if phase_name == list(phases.keys())[0]:
                    y_ticks.append(i)
                    y_tick_labels.append(f"{test_name} ({phase_name})")

            self.axes.set_yticks(y_ticks)
            self.axes.set_yticklabels(y_tick_labels)
            self.axes.set_xlabel("Time (seconds)")
            self.axes.set_ylabel("Test Names")
            self.axes.grid(True)

            self.axes.text(1.0, 1.02, f"Overall Utilization: {overall_utilization:.2%}", transform=self.axes.transAxes, horizontalalignment="right", fontsize=9)
            text_position = 1.05
            for worker, utilization in worker_utilization.items():
                self.axes.text(1.0, text_position, f"{worker}: {utilization:.2%}", transform=self.axes.transAxes, horizontalalignment="right", fontsize=9)
                text_position += 0.03

        self.axes.set_title("Timeline of Test Phases per Worker")
        self.draw()


class PlotWindow(QGroupBox):
    def __init__(self):
        super().__init__()
        self.setTitle("Plot")
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.canvas = TestPlotCanvas(self, width=5, height=4, dpi=100)
        layout.addWidget(self.canvas)

    def update_plot(self, run_info: dict):
        run_info = deepcopy(run_info)
        self.canvas.update_plot(run_info)


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


class RunningWindow(QGroupBox):

    def __init__(self):
        self.count = 0
        super().__init__()
        self.setTitle("Running")
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.running_text_label = QLabel("Initializing ...")
        layout.addWidget(self.running_text_label)

    def update_window(self, run_infos: dict):

        run_infos = deepcopy(run_infos)
        test_states = {}
        for test, test_data in run_infos.items():
            start = None
            stop = None
            for phase, run_info in test_data.items():
                if run_info.start is not None and (start is None or run_info.start < start):
                    start = run_info.start
                if run_info.stop is not None and (stop is None or run_info.stop > stop):
                    stop = run_info.stop
            if start is not None and stop is not None and stop > start:
                test_states[test] = stop - start
            else:
                test_states[test] = None

        lines = []
        for test in sorted(test_states):
            if (test_duration := test_states[test]) is None:
                lines.append(f"{test},running")
            else:
                lines.append(f"{test},{test_duration:.2f}")

        filled_block = "█"
        blink = filled_block if self.count % 2 == 0 else " "
        lines.append(f"{blink}")
        self.running_text_label.setText("\n".join(lines))
        self.count += 1


class CentralWindow(QWidget):
    def __init__(self):
        super().__init__()

        layout = QHBoxLayout()
        self.running_window = RunningWindow()
        self.plot_window = PlotWindow()
        layout.addWidget(self.plot_window, stretch=1)  # expand to fill the available space
        layout.addWidget(self.running_window)
        self.setLayout(layout)


class VisualizationQt(QMainWindow):
    _update_signal = Signal()

    def __init__(self):
        super().__init__()

        self.setWindowTitle(application_name)

        # restore window position and size
        pref = get_pref()
        x, y, width, height = pref.window_x, pref.window_y, pref.window_width, pref.window_height
        if x > 0 and y > 0 and width > 0 and height > 0:
            self.setGeometry(pref.window_x, pref.window_y, pref.window_width, pref.window_height)

        self.central_window = CentralWindow()
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
        run_infos = get_most_recent_run_info()
        self.central_window.running_window.update_window(run_infos)
        self.central_window.plot_window.update_plot(run_infos)

    def closeEvent(self, event):
        pref = get_pref()

        pref.window_x = self.x()
        frame_height = self.frameGeometry().height() - self.geometry().height()
        pref.window_y = self.y() + frame_height
        pref.window_width = self.width()
        pref.window_height = self.height()

        self.observer.stop()
        self.periodic_updater.request_stop()
        self.observer.join()
        self.periodic_updater.wait()

        event.accept()


def visualize(plot_file_path: Path | None = None):
    app = QApplication([])
    viz_qt = VisualizationQt()
    viz_qt.show()
    app.exec()
