from pathlib import Path

from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QSizePolicy, QApplication
from PySide6.QtCore import Qt
from typeguard import typechecked

from ...pytest_runner.pytest_runner import PytestRunner
from ...pytest_runner.test_list import GetTests
from ...pytest_runner.coverage import compute_per_test_coverage
from ...preferences import get_pref, ParallelismControl
from ...interfaces import RunMode, TestOrder, PyTestFlyExitCode, ScheduledTest
from ...db import PytestProcessInfoDB
from ...logger import get_logger
from ...guid import generate_uuid
from ..gui_util import extract_test_duration

from .control_pushbutton import ControlButton
from .parallelism_control_box import ParallelismControlBox
from .run_mode_control_box import RunModeControlBox

log = get_logger()


class ControlWindow(QGroupBox):
    """Run/Stop controls and parallelism/run-mode selectors for the Run tab."""

    @typechecked()
    def __init__(self, parent, data_dir: Path):
        super().__init__(parent)
        self.data_dir = data_dir

        self.run_guid: str | None = None

        self.setTitle("Control")

        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setLayout(layout)

        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.run_button = ControlButton(self, "Run", True)
        layout.addWidget(self.run_button)
        self.run_button.clicked.connect(self.run)

        self.stop_button = ControlButton(self, "Stop", False)
        layout.addWidget(self.stop_button)
        self.stop_button.clicked.connect(self.stop)

        layout.addStretch()

        self.parallelism_box = ParallelismControlBox(self)
        layout.addWidget(self.parallelism_box)

        self.run_mode_box = RunModeControlBox(self)
        layout.addWidget(self.run_mode_box)

        self.pytest_runner: PytestRunner | None = None
        self.prior_durations: dict[str, float] = {}
        self.num_processes: int = 1

        self.set_fixed_width()  # calculate and set the widget width

    def set_fixed_width(self):
        """Calculate and set a fixed width based on the widest child widget."""
        max_width = max(self.run_button.sizeHint().width(), self.stop_button.sizeHint().width(), self.parallelism_box.sizeHint().width())
        # Add some padding
        max_width += 30
        self.setFixedWidth(max_width)

    def update(self):
        """Enable/disable run and stop buttons based on the runner state."""
        if self.pytest_runner is None or not self.pytest_runner.is_running():
            self.run_button.setEnabled(True)
            self.stop_button.setEnabled(False)
        else:
            self.run_button.setEnabled(False)
            self.stop_button.setEnabled(True)

    def run(self):
        """Discover tests and launch a new :class:`PytestRunner`."""
        get_tests = GetTests()
        get_tests.start()

        pref = get_pref()
        refresh_rate = pref.refresh_rate
        self.run_guid = generate_uuid()

        if self.pytest_runner is not None and self.pytest_runner.is_running():
            self.pytest_runner.stop()
            self.pytest_runner.join()

        processes = 1 if pref.parallelism == ParallelismControl.SERIAL else pref.processes

        while get_tests.is_alive():
            get_tests.join(1)
            QApplication.processEvents()  # keep the GUI at least somewhat responsive while we gather the tests
        get_tests.join()

        tests = get_tests.get_tests()

        # Query prior results once (used by both RESUME filtering and failed-first ordering)
        with PytestProcessInfoDB(self.data_dir) as db:
            prior_results = db.query()  # most recent run

        tests = self._filter_for_resume(tests, prior_results, pref)

        # Reorder so previously-failed tests run first (within their singleton group)
        tests = self._reorder_failed_first(tests, prior_results)

        # Compute prior durations for ETA estimation
        self.prior_durations = self._compute_prior_durations(prior_results)
        self.num_processes = processes

        # Populate coverage/duration for coverage-efficiency ordering
        if pref.test_order == TestOrder.COVERAGE:
            tests = self._apply_coverage_order(tests)
            tests.sort()

        self.pytest_runner = PytestRunner(self.run_guid, tests, processes, self.data_dir, refresh_rate)
        self.pytest_runner.start()

        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)

    def _filter_for_resume(self, tests, prior_results, pref):
        """Filter out already-passed tests when running in RESUME mode.

        :param tests: List of scheduled tests.
        :param prior_results: List of prior PytestProcessInfo records.
        :param pref: User preferences object.
        :return: Filtered list of tests.
        """
        if pref.run_mode == RunMode.RESUME:
            passed = {r.name for r in prior_results if r.exit_code == PyTestFlyExitCode.OK}
            tests = [t for t in tests if t.node_id not in passed]
        return tests

    def _reorder_failed_first(self, tests, prior_results):
        """Reorder tests so previously-failed ones run first (within their singleton group).

        :param tests: List of scheduled tests.
        :param prior_results: List of prior PytestProcessInfo records.
        :return: Reordered list of tests.
        """
        if prior_results:
            passed = {r.name for r in prior_results if r.exit_code == PyTestFlyExitCode.OK}
            prior_names = {r.name for r in prior_results}
            failed = prior_names - passed
            tests = sorted(tests, key=lambda t: (t.singleton, t.node_id not in failed))
        return tests

    def _apply_coverage_order(self, tests):
        """Replace ScheduledTest objects with ones carrying prior duration and coverage data.

        When both values are available the existing ``ScheduledTest.__lt__`` sorts
        by lines-per-second efficiency.  Tests without prior data keep ``None``
        and fall back to alphabetical ordering.

        :param tests: List of scheduled tests.
        :return: New list with duration/coverage populated where available.
        """
        per_test_cov = compute_per_test_coverage(self.data_dir, [t.node_id for t in tests])
        return [
            ScheduledTest(
                node_id=t.node_id,
                singleton=t.singleton,
                duration=self.prior_durations.get(t.node_id),
                coverage=per_test_cov.get(t.node_id),
            )
            for t in tests
        ]

    def _compute_prior_durations(self, prior_results):
        """Compute durations from prior results for ETA estimation.

        :param prior_results: List of prior PytestProcessInfo records.
        :return: Dictionary mapping test name to duration in seconds.
        """
        durations = {}
        prior_by_name: dict[str, list] = {}
        for r in prior_results:
            prior_by_name.setdefault(r.name, []).append(r)
        for name, infos in prior_by_name.items():
            start, end = extract_test_duration(infos)
            if start is not None and end is not None:
                durations[name] = end - start
        return durations

    def stop(self):
        """Stop the currently running test suite."""
        self.pytest_runner.stop()
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.run_guid = None
