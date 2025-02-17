from copy import deepcopy

import numpy as np
from PySide6.QtWidgets import QGroupBox, QVBoxLayout

from .progress_bar import ProgressBars, Process


class ProgressWindow(QGroupBox):
    def __init__(self):
        super().__init__()
        self.setTitle("Progress")
        self.progress_layout = QVBoxLayout()
        self.setLayout(self.progress_layout)
        self.progress_bars = ProgressBars()
        self.progress_layout.addWidget(self.progress_bars)
        self.progress_layout.addStretch()
        self.update_progress()

    def update_progress(self):
        processes = [
            Process("Process 1", self.progress_bars.timeline_start, self.progress_bars.timeline_start + np.timedelta64(2, "m")),
            Process("Process 2", self.progress_bars.timeline_start + np.timedelta64(1, "m"), self.progress_bars.timeline_start + np.timedelta64(3, "m")),
            Process("Process 3", self.progress_bars.timeline_start + np.timedelta64(2, "m"), self.progress_bars.timeline_start + np.timedelta64(4, "m")),
        ]
        self.progress_bars.update_processes(processes)
