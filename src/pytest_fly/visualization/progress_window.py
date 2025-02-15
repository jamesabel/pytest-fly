from copy import deepcopy

import numpy as np
from PySide6.QtWidgets import QGroupBox, QVBoxLayout

from .utilization import calculate_utilization


class PlotWindow(QGroupBox):
    def __init__(self):
        super().__init__()
        self.setTitle("Plot")
        layout = QVBoxLayout()
        self.setLayout(layout)
        # self.canvas = TestPlotCanvas(self, width=5, height=4, dpi=100)
        # layout.addWidget(self.canvas)

    def update_plot(self, run_info: dict):
        run_info = deepcopy(run_info)
        # self.canvas.update_plot(run_info)
        # self.canvas.setMinimumSize(self.canvas.sizeHint())


# class TestPlotCanvas(FigureCanvas):
#     def __init__(self, parent=None, width=5, height=4, dpi=100):
#         fig = Figure(figsize=(width, height), dpi=dpi)
#         self.axes = fig.add_subplot(111)
#         super().__init__(fig)
#         self.setParent(parent)
#         fig.subplots_adjust(left=0.25)  # Adjust the left margin
#
#     def update_plot(self, run_info: dict):
#         """
#         Update the plot with the most recent data from the database.
#         """
#
#         if len(run_info) > 0:
#
#             sorted_data = dict(sorted(run_info.items(), key=lambda x: x[0], reverse=True))
#             worker_utilization, overall_utilization = calculate_utilization(sorted_data)
#             if len(starts := [phase.start for test in sorted_data.values() for phase in test.values()]) > 0:
#                 earliest_start = min(starts)
#             else:
#                 earliest_start = 0
#
#             workers = set(info.worker_id for test in sorted_data.values() for info in test.values())
#             colors = plt.cm.jet(np.linspace(0, 1, len(workers)))
#             worker_colors = dict(zip(workers, colors))
#
#             self.axes.clear()
#
#             y_ticks, y_tick_labels = [], []
#             for i, (test_name, phases) in enumerate(sorted_data.items()):
#                 for phase_name, phase_info in phases.items():
#                     relative_start = phase_info.start - earliest_start
#                     relative_stop = phase_info.stop - earliest_start
#                     worker_id = phase_info.worker_id
#
#                     self.axes.plot([relative_start, relative_stop], [i, i], color=worker_colors[worker_id], marker="o", markersize=4)
#
#                     # if phase_name == list(phases.keys())[0]:
#                     y_ticks.append(i)
#                     y_tick_labels.append(f"{test_name} ({phase_name})")
#
#             self.axes.set_yticks(y_ticks)
#             self.axes.set_yticklabels(y_tick_labels)
#             self.axes.set_xlabel("Time (seconds)")
#             self.axes.set_ylabel("Test Names")
#             self.axes.grid(True)
#
#             self.axes.text(1.0, 1.02, f"Overall Utilization: {overall_utilization:.2%}", transform=self.axes.transAxes, horizontalalignment="right", fontsize=6)
#             text_position = 1.05
#             for worker, utilization in worker_utilization.items():
#                 self.axes.text(1.0, text_position, f"{worker}: {utilization:.2%}", transform=self.axes.transAxes, horizontalalignment="right", fontsize=6)
#                 text_position += 0.03
#
#             # Adjust figure size based on the number of y-ticks
#             fig_height = max(4, int(len(y_ticks) / 10.0))
#             self.figure.set_size_inches(10, fig_height)
#
#         self.axes.set_title("Timeline of Test Phases per Worker")
#         self.draw()
