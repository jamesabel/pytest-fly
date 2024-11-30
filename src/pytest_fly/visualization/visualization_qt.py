from pathlib import Path


from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox
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


class DatabaseChangeHandler(FileSystemEventHandler):
    def __init__(self, update_callback):
        self.update_callback = update_callback
        super().__init__()

    def on_modified(self, event):
        if Path(event.src_path).name == fly_db_file_name:
            self.update_callback()


class PlotWindow(QGroupBox):
    def __init__(self):
        super().__init__()
        self.setTitle("Plot")
        layout = QVBoxLayout()
        self.setLayout(layout)


class TestPlotCanvas(FigureCanvas):
    def __init__(self, parent=None, width=5, height=4, dpi=100):
        fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = fig.add_subplot(111)
        super().__init__(fig)
        self.setParent(parent)


class RunningWindow(QGroupBox):
    def __init__(self):
        super().__init__()
        self.setTitle("Running")
        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.addWidget(QLabel("Running"))


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
    def __init__(self):
        super().__init__()

        self.update_count = 0

        self.setWindowTitle(application_name)

        # restore window position and size
        pref = get_pref()
        x, y, width, height = pref.window_x, pref.window_y, pref.window_width, pref.window_height
        if x > 0 and y > 0 and width > 0 and height > 0:
            self.setGeometry(pref.window_x, pref.window_y, pref.window_width, pref.window_height)

        self.central_window = CentralWindow()
        self.setCentralWidget(self.central_window)

        plot_window_layout = self.central_window.plot_window.layout()
        self.canvas = TestPlotCanvas(self, width=5, height=4, dpi=100)
        plot_window_layout.addWidget(self.canvas)

        self.update_plot()

        # start file watcher
        self.event_handler = DatabaseChangeHandler(self.update_plot)
        self.observer = Observer()
        db_path = get_db_path()
        self.observer.schedule(self.event_handler, path=str(db_path.parent), recursive=False)  # watchdog watches a directory
        self.observer.start()

    def update_plot(self):

        self.update_count += 1

        run_info = get_most_recent_run_info()

        sorted_data = dict(sorted(run_info.items(), key=lambda x: x[0], reverse=True))
        worker_utilization, overall_utilization = calculate_utilization(sorted_data)
        if len(starts := [phase.start for test in sorted_data.values() for phase in test.values()]) > 0:
            earliest_start = min(starts)
        else:
            earliest_start = 0

        workers = set(info.worker_id for test in sorted_data.values() for info in test.values())
        colors = plt.cm.jet(np.linspace(0, 1, len(workers)))
        worker_colors = dict(zip(workers, colors))

        self.canvas.axes.clear()

        yticks, yticklabels = [], []
        for i, (test_name, phases) in enumerate(sorted_data.items()):
            for phase_name, phase_info in phases.items():
                relative_start = phase_info.start - earliest_start
                relative_stop = phase_info.stop - earliest_start
                worker_id = phase_info.worker_id

                self.canvas.axes.plot([relative_start, relative_stop], [i, i], color=worker_colors[worker_id], marker="o", markersize=4, label=worker_id if phase_name == "setup" else "")

                if phase_name == list(phases.keys())[0]:
                    yticks.append(i)
                    yticklabels.append(test_name)

        self.canvas.axes.set_yticks(yticks)
        self.canvas.axes.set_yticklabels(yticklabels)
        self.canvas.axes.set_xlabel("Time (seconds)")
        self.canvas.axes.set_ylabel("Test Names")
        self.canvas.axes.set_title(f"Timeline of Test Phases per Worker ({self.update_count})")
        self.canvas.axes.grid(True)

        self.canvas.axes.text(1.0, 1.02, f"Overall Utilization: {overall_utilization:.2%}", transform=self.canvas.axes.transAxes, horizontalalignment="right", fontsize=9)
        text_position = 1.05
        for worker, utilization in worker_utilization.items():
            self.canvas.axes.text(1.0, text_position, f"{worker}: {utilization:.2%}", transform=self.canvas.axes.transAxes, horizontalalignment="right", fontsize=9)
            text_position += 0.03

        self.canvas.draw()

    def closeEvent(self, event):
        pref = get_pref()

        pref.window_x = self.x()
        frame_height = self.frameGeometry().height() - self.geometry().height()
        pref.window_y = self.y() + frame_height
        pref.window_width = self.width()
        pref.window_height = self.height()

        self.observer.stop()
        event.accept()


def visualize(plot_file_path: Path | None = None):
    app = QApplication([])
    viz_qt = VisualizationQt()
    viz_qt.show()
    app.exec()
