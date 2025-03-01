from datetime import timedelta

from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QSizePolicy

import humanize

from ..gui_util import PlainTextWidget, get_text_dimensions
from ...model import exit_code_to_string, PytestKey
from pytest_fly.common.classes import PytestStatus


class StatusWindow(QGroupBox):

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

    def update_status(self, status: PytestStatus):
        pytest_key = PytestKey(name=status.name, state=status.state)
        self.statuses[pytest_key] = status
        most_recent_statuses = {}
        for key, status in self.statuses.items():
            if key.name not in most_recent_statuses or status.time_stamp > most_recent_statuses[key.name].time_stamp:
                most_recent_statuses[key.name] = status
        lines = []
        for name, status in most_recent_statuses.items():
            if (exit_code := status.exit_code) is None:
                lines.append(f"{name},{status.state.name}")
            else:
                lines.append(f"{name},{status.state.name},{exit_code_to_string(exit_code)}")

        # add total time so far to status
        min_time_stamp = min(status.time_stamp for status in most_recent_statuses.values())
        max_time_stamp = max(status.time_stamp for status in most_recent_statuses.values())
        overall_time = max_time_stamp - min_time_stamp

        lines.append(f"Total time: {humanize.precisedelta(timedelta(seconds=overall_time))}")

        text = "\n".join(lines)

        text_dimensions = get_text_dimensions(text, True)
        self.setFixedSize(text_dimensions)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.status_widget.set_text("\n".join(lines))
