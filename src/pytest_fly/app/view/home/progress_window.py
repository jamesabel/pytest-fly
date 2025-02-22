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
        self.statuses = {}
        self.progress_bars = {}
        self.setTitle("Progress")
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setLayout(layout)

    def update_status(self, status: PytestStatus):
        layout = self.layout()

        # update status list in-place
        if status.name not in self.statuses:
            self.statuses[status.name] = [status]
        else:
            self.statuses[status.name].append(status)
        self.statuses[status.name].sort(key=lambda s: s.time_stamp)  # keep sorted by time (probably unnecessary)

        min_time_stamp_for_all_tests, max_time_stamp_for_all_tests = get_overall_time_window(self.statuses)

        start_time = min([s.time_stamp for s in self.statuses[status.name]])
        end_time = max([s.time_stamp for s in self.statuses[status.name]])

        if status.name not in self.progress_bars:
            progress_bar = PytestProgressBar(start_time, end_time, min_time_stamp_for_all_tests, max_time_stamp_for_all_tests, status.name, self)
            self.progress_bars[status.name] = progress_bar
            layout.addWidget(progress_bar)
        for progress_bar in self.progress_bars.values():
            progress_bar.update_time_window(min_time_stamp_for_all_tests, max_time_stamp_for_all_tests)
        self.progress_bars[status.name].update_status(start_time, end_time, min_time_stamp_for_all_tests, max_time_stamp_for_all_tests)
