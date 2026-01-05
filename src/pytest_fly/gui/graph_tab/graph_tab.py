from collections import defaultdict
from pprint import pprint

from PySide6.QtWidgets import QGroupBox, QVBoxLayout
from PySide6.QtCore import Qt
from typeguard import typechecked

from ...interfaces import PytestProcessInfo
from .progress_bar import PytestProgressBar


class GraphTab(QGroupBox):
    def __init__(self):
        super().__init__()
        self.setTitle("Progress")
        self.progress_bars = {}
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setLayout(layout)

    @typechecked()
    def update_pytest_process_info(self, pytest_process_infos: list[PytestProcessInfo]) -> None:

        # organize statuses by test name
        statuses = defaultdict(list)
        for info in pytest_process_infos:
            statuses[info.name].append(info)

        # get overall time window
        min_time_stamp = max_time_stamp = None
        for info in pytest_process_infos:
            if min_time_stamp is None or info.time_stamp < min_time_stamp:
                min_time_stamp = info.time_stamp
            if max_time_stamp is None or info.time_stamp > max_time_stamp:
                max_time_stamp = info.time_stamp

        layout = self.layout()

        for test_name, infos in statuses.items():
            if test_name in self.progress_bars:
                progress_bar = self.progress_bars[test_name]
                progress_bar.update_pytest_process_info(infos, min_time_stamp, max_time_stamp)
            else:
                # add a new progress bar
                progress_bar = PytestProgressBar(infos, min_time_stamp, max_time_stamp)
                layout.addWidget(progress_bar)
                self.progress_bars[test_name] = progress_bar
