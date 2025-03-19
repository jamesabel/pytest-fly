import time
from collections import defaultdict

from PySide6.QtWidgets import QGroupBox, QVBoxLayout
from PySide6.QtCore import Qt, QTimer

from ....common import PytestProcessState, PytestProcessInfo
from ...preferences import get_pref
from .progress_bar import PytestProgressBar


def get_overall_time_window(statuses: dict[str, list[PytestProcessInfo]]) -> tuple[float, float]:
    min_time_stamp_for_all_tests = None
    max_time_stamp_for_all_tests = None
    for status_list in statuses.values():
        for status in status_list:
            if status.start is not None and (min_time_stamp_for_all_tests is None or status.time_stamp < min_time_stamp_for_all_tests):
                min_time_stamp_for_all_tests = status.time_stamp
            if status.end is not None and (max_time_stamp_for_all_tests is None or status.time_stamp > max_time_stamp_for_all_tests):
                max_time_stamp_for_all_tests = status.time_stamp
    if min_time_stamp_for_all_tests is None:
        min_time_stamp_for_all_tests = time.time()
    if max_time_stamp_for_all_tests is None:
        max_time_stamp_for_all_tests = time.time()
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

        # Initialize and start the timer
        refresh_rate = get_pref().refresh_rate
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(lambda: self.update_status(None))
        self.update_timer.start(int(round(refresh_rate * 1000)))

    def reset(self):
        self.statuses = defaultdict(list)
        for progress_bar in self.progress_bars.values():
            progress_bar.deleteLater()
        self.progress_bars = {}

    def update_status(self, status: PytestProcessInfo):
        layout = self.layout()

        if status is not None:
            if status.state == PytestProcessState.QUEUED:
                self.statuses[status.name].clear()  # in case of multiple runs
            self.statuses[status.name].append(status)

            status_list = self.statuses[status.name]
        else:
            status_list = []

        min_time_stamp_for_all_tests, max_time_stamp_for_all_tests = get_overall_time_window(self.statuses)

        if status is not None and status.name not in self.progress_bars:
            # add a new progress bar
            progress_bar = PytestProgressBar(status_list, min_time_stamp_for_all_tests, max_time_stamp_for_all_tests, self)
            self.progress_bars[status.name] = progress_bar
            layout.addWidget(progress_bar)

        for progress_bar in self.progress_bars.values():
            # update time window for all progress bars
            progress_bar.update_time_window(min_time_stamp_for_all_tests, max_time_stamp_for_all_tests)

        # update progress bar for this particular test
        if status is not None:
            self.progress_bars[status.name].update_status(status_list)

        # stop the timer if there are no tests running
        if all(status_list[-1].state == PytestProcessState.FINISHED for status_list in self.statuses.values()):
            self.update_timer.stop()
        else:
            refresh_rate = get_pref().refresh_rate
            self.update_timer.start(int(round(refresh_rate * 1000)))
