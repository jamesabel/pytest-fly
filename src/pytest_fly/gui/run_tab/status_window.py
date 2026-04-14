import time
from collections import defaultdict
from datetime import timedelta

from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QSizePolicy

import humanize

from ...gui.gui_util import PlainTextWidget
from ...interfaces import PytestRunnerState
from ...tick_data import TickData


class StatusWindow(QGroupBox):
    """Displays an aggregate status summary (pass/fail counts, elapsed time, etc.)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setTitle("Status")
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.status_widget = PlainTextWidget(self, "Loading...")
        layout.addWidget(self.status_widget)

    def update_tick(self, tick: TickData):
        """
        Rebuild the status text from pre-computed tick data.

        :param tick: Pre-computed data for this refresh cycle.
        """

        counts: dict[PytestRunnerState, int] = defaultdict(int)
        for test_name, run_state in tick.run_states.items():
            counts[run_state.get_state()] += 1

        min_time_stamp = tick.min_time_stamp_started
        max_time_stamp = tick.max_time_stamp_started

        if len(tick.infos_by_name) > 0:
            total_tests = len(tick.infos_by_name)
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

            # add current code coverage
            if tick.coverage_history:
                latest_coverage = tick.coverage_history[-1][1]
                cov_text = f"Coverage: {latest_coverage:.1%}"
                if tick.total_lines > 0:
                    cov_text += f"  ({tick.covered_lines}/{tick.total_lines} lines)"
                lines.append(cov_text)

            # estimated time remaining based on prior run durations
            if tick.prior_durations and (counts[PytestRunnerState.QUEUED] + counts[PytestRunnerState.RUNNING]) > 0:
                remaining_seconds = 0.0
                now = time.time()
                for test_name, run_state in tick.run_states.items():
                    state = run_state.get_state()
                    prior = tick.prior_durations.get(test_name, 0.0)
                    if state == PytestRunnerState.QUEUED:
                        remaining_seconds += prior
                    elif state == PytestRunnerState.RUNNING:
                        infos = tick.infos_by_name.get(test_name, [])
                        started_at = next((i.time_stamp for i in infos if i.pid is not None), None)
                        if started_at is not None:
                            remaining_seconds += max(0.0, prior - (now - started_at))
                if remaining_seconds > 0 and tick.num_processes > 0:
                    wall_clock = remaining_seconds / tick.num_processes
                    lines.append(f"Estimated remaining: {humanize.precisedelta(timedelta(seconds=wall_clock))}")
        else:
            lines = ["Calculating..."]

        self.status_widget.set_text("\n".join(lines))
