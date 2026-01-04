from datetime import timedelta
from collections import defaultdict

from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QSizePolicy

import humanize
from mypy.dmypy_os import OpenProcess

from ...gui.gui_util import PlainTextWidget
from ...interfaces import PytestProcessInfo, PytestRunnerState
from ...pytest_runner.pytest_runner import PytestRunState


class StatusWindow(QGroupBox):

    def __init__(self, parent):
        super().__init__(parent)
        self.setTitle("Status")
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.status_widget = PlainTextWidget(self, "Loading...")
        layout.addWidget(self.status_widget)

    def update_status(self, pytest_process_infos: list[PytestProcessInfo]):
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

        if len(processes_infos) > 0:
            lines = [f"{len(processes_infos)} tests", ""]

            # get current pass rate
            current_pass_count = counts[PytestRunnerState.PASS]
            current_fail_count = counts[PytestRunnerState.FAIL]
            total_completed = current_pass_count + current_fail_count
            prefix = "Pass rate: "
            if total_completed > 0:
                pass_rate = current_pass_count / total_completed
                lines.append(f"{prefix}{current_pass_count}/{total_completed} ({pass_rate:.2%})")
            else:
                lines.append(f"{prefix}(calculating...)")
            lines.append("")  # space

            for state in [PytestRunnerState.PASS, PytestRunnerState.FAIL, PytestRunnerState.QUEUED, PytestRunnerState.RUNNING, PytestRunnerState.TERMINATED]:
                count = counts[state]
                if len(processes_infos) > 0:
                    lines.append(f"{state}: {count} ({count / len(processes_infos):.2%})")
                else:
                    lines.append(f"{state}: {count}")

            # add total time so far to status
            if min_time_stamp is not None and max_time_stamp is not None:
                overall_time = max_time_stamp - min_time_stamp
                lines.append(f"Total time: {humanize.precisedelta(timedelta(seconds=overall_time))}")
        else:
            lines = ["Tests not yet run. Please run the tests."]

        self.status_widget.set_text("\n".join(lines))
