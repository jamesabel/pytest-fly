from datetime import timedelta
from collections import defaultdict

from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QSizePolicy

import humanize

from ..gui_util import PlainTextWidget, get_text_dimensions
from ....common import PytestProcessState
from pytest_fly.common.classes import PytestStatus


class SummaryWindow(QGroupBox):

    def __init__(self):
        super().__init__()
        self.statuses = {}
        self.setTitle("Status")
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.status_widget = PlainTextWidget()
        self.status_widget.set_text("")
        layout.addWidget(self.status_widget)
        layout.addStretch()
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(self.status_widget.size())

    def update_summary(self, status: PytestStatus):
        """
        Update the status window with the new status.

        param status: The new status to add to the window.
        """

        # update with this particular status
        self.statuses[status.name] = status

        # get statistics
        counts = defaultdict(int)
        min_time_stamp = None
        max_time_stamp = None
        for status in self.statuses.values():
            counts[status.state] += 1
            if min_time_stamp is None or status.time_stamp < min_time_stamp:
                min_time_stamp = status.time_stamp
            if max_time_stamp is None or status.time_stamp > max_time_stamp:
                max_time_stamp = status.time_stamp

        # convert statistics to text
        total_count = len(self.statuses)
        lines = []
        for status_name in [PytestProcessState.QUEUED, PytestProcessState.RUNNING, PytestProcessState.FINISHED, PytestProcessState.TERMINATED, PytestProcessState.UNKNOWN]:
            count = counts[status_name]
            lines.append(f"{status_name}: {count} ({count/total_count:.2%})")
        lines.append(f"Total: {total_count}")

        # add total time so far to status
        overall_time = max_time_stamp - min_time_stamp

        lines.append(f"Total time: {humanize.precisedelta(timedelta(seconds=overall_time))}")

        text = "\n".join(lines)

        text_dimensions = get_text_dimensions(text, True)
        self.setFixedSize(text_dimensions)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.status_widget.set_text("\n".join(lines))
