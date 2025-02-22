from collections import defaultdict

from PySide6.QtWidgets import QGroupBox, QVBoxLayout
from PySide6.QtCore import Qt


from .progress_bar import PytestProgressBar
from ...model import PytestStatus


class ProgressWindow(QGroupBox):
    def __init__(self):
        super().__init__()
        self.statuses = defaultdict(list)
        self.progress_bars = {}
        self.setTitle("Progress")
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setLayout(layout)

    def update_status(self, status: PytestStatus):
        layout = self.layout()
        if status.name not in self.statuses:
            progress_bar = PytestProgressBar(0, 2, 6, status.name, self)
            self.progress_bars[status.name] = progress_bar
            layout.addWidget(progress_bar)
        status_list = self.statuses[status.name]
        status_list.append(status)
        status_list.sort(key=lambda s: s.time_stamp)  # keep sorted
        self.statuses[status.name] = status_list
