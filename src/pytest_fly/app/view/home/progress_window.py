from collections import defaultdict

from PySide6.QtWidgets import QGroupBox, QVBoxLayout
from PySide6.QtCore import Qt


from .progress_bar import PytestProgressBar
from ...model import PytestStatus


def get_overall_time_window(statuses: dict[str, list[PytestStatus]]) -> tuple[float, float]:
    min_time_stamp_for_all_tests = None
    max_time_stamp_for_all_tests = None
    for status_list in statuses.values():
        for status in status_list:
            if min_time_stamp_for_all_tests is None or status.time_stamp < min_time_stamp_for_all_tests:
                min_time_stamp_for_all_tests = status.time_stamp
            if max_time_stamp_for_all_tests is None or status.time_stamp > max_time_stamp_for_all_tests:
                max_time_stamp_for_all_tests = status.time_stamp
    return min_time_stamp_for_all_tests, max_time_stamp_for_all_tests


class ProgressWindow(QGroupBox):
    def __init__(self):
        super().__init__()
        self.statuses = defaultdict(list)
        self.progress_bars = {}
        self.setTitle("Progress")
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setLayout(layout)

    def reset(self):
        self.statuses = defaultdict(list)
        for progress_bar in self.progress_bars.values():
            progress_bar.deleteLater()
        self.progress_bars = {}

    def update_status(self, status: PytestStatus):
        layout = self.layout()

        self.statuses[status.name].append(status)
        self.statuses[status.name].sort(key=lambda s: s.time_stamp)  # keep sorted by time (probably unnecessary)

        status_list = self.statuses[status.name]
        min_time_stamp_for_all_tests, max_time_stamp_for_all_tests = get_overall_time_window(self.statuses)

        if status.name not in self.progress_bars:
            # add a new progress bar
            progress_bar = PytestProgressBar(status_list, min_time_stamp_for_all_tests, max_time_stamp_for_all_tests, self)
            self.progress_bars[status.name] = progress_bar
            layout.addWidget(progress_bar)
        for progress_bar in self.progress_bars.values():
            # update time window for all progress bars
            progress_bar.update_time_window(min_time_stamp_for_all_tests, max_time_stamp_for_all_tests)
        # update progress bar for this particular test
        self.progress_bars[status.name].update_status(status_list, min_time_stamp_for_all_tests, max_time_stamp_for_all_tests)
