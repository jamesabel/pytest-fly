from datetime import timedelta
from collections import defaultdict
import time

from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QSizePolicy

import humanize

from ...gui.gui_util import PlainTextWidget, get_text_dimensions
from ...interfaces import PytestProcessInfo
from ...pytest_runner.pytest_runner import PytestRunState
from ...pytest_runner.const import PytestProcessState


class SummaryWindow(QGroupBox):

    def __init__(self):
        super().__init__()
        self.setTitle("Status")
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.status_widget = PlainTextWidget()
        self.status_widget.set_text("")
        layout.addWidget(self.status_widget)
        layout.addStretch()
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(self.status_widget.size())

    def update_summary(self, pytest_process_infos: list[PytestProcessInfo]):
        """
        Update the status window with the new status.

        param status: The new status to add to the window.
        """

        processes_infos = defaultdict(list)
        for pytest_process_info in pytest_process_infos:
            processes_infos[pytest_process_info.name].append(pytest_process_info)

        counts = defaultdict(int)
        for row_number, test_name in enumerate(processes_infos):
            process_infos = processes_infos[test_name]
            pytest_run_state = PytestRunState(process_infos)
            counts[pytest_run_state.state] += 1

        min_time_stamp = None
        max_time_stamp = None
        for process_info in pytest_process_infos:
            if process_info.pid is not None:
                if min_time_stamp is None or process_info.time_stamp < min_time_stamp:
                    min_time_stamp = process_info.time_stamp
                if max_time_stamp is None or process_info.time_stamp > max_time_stamp:
                    max_time_stamp = process_info.time_stamp

        lines = [f"{len(counts)} tests"]
        for state, count in counts.items():
            lines.append(f"{state}: {count} ({count / len(counts):.2%})")

        # add total time so far to status
        overall_time = max_time_stamp - min_time_stamp

        lines.append(f"Total time: {humanize.precisedelta(timedelta(seconds=overall_time))}")

        text = "\n".join(lines)

        text_dimensions = get_text_dimensions(text, True)
        self.setFixedSize(text_dimensions)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.status_widget.set_text("\n".join(lines))
