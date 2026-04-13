from collections import defaultdict
from datetime import timedelta

from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QSizePolicy

import humanize

from ...gui.gui_util import PlainTextWidget, group_process_infos_by_name, compute_time_window
from ...interfaces import PytestProcessInfo, PytestRunnerState
from ...pytest_runner.pytest_runner import PytestRunState


class StatusWindow(QGroupBox):
    """Displays an aggregate status summary (pass/fail counts, elapsed time, etc.)."""

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
        Rebuild the status text from the latest process info records.

        :param pytest_process_infos: All process info records for the current run.
        """

        infos_by_name = group_process_infos_by_name(pytest_process_infos)

        counts: dict[PytestRunnerState, int] = defaultdict(int)
        for test_name, process_infos in infos_by_name.items():
            pytest_run_state = PytestRunState(process_infos)
            counts[pytest_run_state.get_state()] += 1

        min_time_stamp, max_time_stamp = compute_time_window(pytest_process_infos, require_pid=True)

        if len(infos_by_name) > 0:
            total_tests = len(infos_by_name)
            lines = [f"{total_tests} tests", ""]

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
                lines.append(f"{state}: {count} ({count / total_tests:.2%})")

            # add total time so far to status
            if min_time_stamp is not None and max_time_stamp is not None:
                overall_time = max_time_stamp - min_time_stamp
                lines.append(f"Total time: {humanize.precisedelta(timedelta(seconds=overall_time))}")
        else:
            lines = ["Tests not yet run. Please run the tests."]

        self.status_widget.set_text("\n".join(lines))
