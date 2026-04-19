"""
Control window — Run/Stop buttons and parallelism/run-mode selectors.

Houses the run-preparation logic: test discovery, RESUME filtering,
failed-first reordering, and coverage-efficiency ordering.
"""

import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QGroupBox, QSizePolicy, QVBoxLayout
from typeguard import typechecked

from ...db import PytestProcessInfoDB
from ...guid import generate_uuid
from ...interfaces import PutVersionInfo, PyTestFlyExitCode, RunMode, ScheduledTest, TestOrder
from ...logger import get_logger
from ...preferences import ParallelismControl, get_pref
from ...put_version import detect_put_version
from ...pytest_runner.coverage import compute_per_test_coverage
from ...pytest_runner.pytest_runner import PytestRunner
from ...pytest_runner.test_list import GetTests
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
        self.stop_button.setToolTip("Wait for the running tests and then stop")
        layout.addWidget(self.stop_button)
        self.stop_button.clicked.connect(self.soft_stop)

        self.force_stop_button = ControlButton(self, "Force Stop", False)
        self.force_stop_button.setToolTip("Immediately terminate all running tests")
        layout.addWidget(self.force_stop_button)
        self.force_stop_button.clicked.connect(self.force_stop)

        layout.addStretch()

        self.parallelism_box = ParallelismControlBox(self)
        layout.addWidget(self.parallelism_box)

        self.run_mode_box = RunModeControlBox(self)
        layout.addWidget(self.run_mode_box)

        self.pytest_runner: PytestRunner | None = None
        self.prior_durations: dict[str, float] = {}
        self.num_processes: int = 1
        self._soft_stop_requested: bool = False
        self.current_run_start: float | None = None
        self.singleton_names: set[str] = set()
        self.put_version_info: PutVersionInfo | None = None

        self.set_fixed_width()  # calculate and set the widget width

    def set_fixed_width(self):
        """Calculate and set a fixed width based on the widest child widget."""
        max_width = max(self.run_button.sizeHint().width(), self.stop_button.sizeHint().width(), self.force_stop_button.sizeHint().width(), self.parallelism_box.sizeHint().width())
        # Add some padding
        max_width += 30
        self.setFixedWidth(max_width)

    def update(self):
        """Enable/disable run, stop, and force stop buttons based on the runner state."""
        if self.pytest_runner is None or not self.pytest_runner.is_running():
            self.run_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.force_stop_button.setEnabled(False)
            self._soft_stop_requested = False
        elif self._soft_stop_requested:
            self.run_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            self.force_stop_button.setEnabled(True)
        else:
            self.run_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.force_stop_button.setEnabled(True)

    def run(self):
        """Discover tests and launch a new :class:`PytestRunner`."""
        pref = get_pref()

        # Resolve the project root from the preference override (if any) and detect the
        # program-under-test version before starting collection so we can pass the path
        # into GetTests for consistent discovery.
        project_root = Path(pref.target_project_path).resolve() if pref.target_project_path else Path.cwd()
        self.put_version_info = detect_put_version(project_root)
        log.info(f"PUT detected: {self.put_version_info}")

        get_tests = GetTests(test_dir=project_root)
        get_tests.start()

        refresh_rate = pref.refresh_rate
        self.run_guid = generate_uuid()
        # Capture start time before any prior records are copied so the graph
        # time axis can use it as the origin, rather than trying to infer it
        # from DB records (copied RESUME records also have exit_code == NONE,
        # which made the DB-derived origin fall back to a prior-run timestamp).
        self.current_run_start = time.time()

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
            last_pass_data = db.query_last_pass()  # most recent passing run per test

        # CHECK mode: behave like RESUME if the PUT fingerprint matches the prior run, else RESTART.
        effective_mode = pref.run_mode
        if pref.run_mode == RunMode.CHECK:
            effective_mode = self._resolve_check_mode(prior_results)

        all_node_ids = {t.node_id for t in tests}
        tests = self._filter_for_resume(tests, prior_results, effective_mode)

        # In RESUME mode (or CHECK-as-RESUME), copy the complete prior-run records for
        # previously-passed tests into the current run so they appear in all GUI tabs
        # (table, graph, status) with their original data (runtime, CPU, memory, output, etc.).
        # Timestamps are shifted uniformly so the copied records fall within the current
        # run's time window; the Progress Graph uses current_run_start as its origin, so
        # records retaining their historical timestamps would render off the visible axis.
        if effective_mode == RunMode.RESUME:
            skipped_node_ids = all_node_ids - {t.node_id for t in tests}
            if skipped_node_ids:
                prior_by_name: dict[str, list] = {}
                for r in prior_results:
                    prior_by_name.setdefault(r.name, []).append(r)
                records_to_copy = [rec for nid in sorted(skipped_node_ids) for rec in prior_by_name.get(nid, [])]
                if records_to_copy:
                    delta = self.current_run_start - min(r.time_stamp for r in records_to_copy)
                    with PytestProcessInfoDB(self.data_dir) as db:
                        for record in records_to_copy:
                            db.write(replace(record, run_guid=self.run_guid, time_stamp=record.time_stamp + delta))

        # Reorder so previously-failed tests run first (within their singleton group).
        # RESTART means "start over" — ignore prior results entirely so execution order
        # matches the alphabetical table display.
        if effective_mode != RunMode.RESTART:
            tests = self._reorder_failed_first(tests, prior_results)

        # Use last-pass durations for ETA estimation (from the most recent passing run)
        self.prior_durations = {name: duration for name, (_, duration) in last_pass_data.items()}
        self.num_processes = processes

        # Populate coverage/duration for coverage-efficiency ordering
        if pref.test_order == TestOrder.COVERAGE:
            tests = self._apply_coverage_order(tests)
            tests.sort()

        self.singleton_names = {t.node_id for t in tests if t.singleton}

        put_label = self.put_version_info.short_label() if self.put_version_info else ""
        put_fp = self.put_version_info.fingerprint() if self.put_version_info else ""
        self.pytest_runner = PytestRunner(self.run_guid, tests, processes, self.data_dir, refresh_rate, put_version=put_label, put_fingerprint=put_fp)
        self.pytest_runner.start()

        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.force_stop_button.setEnabled(True)
        self._soft_stop_requested = False

    def _filter_for_resume(self, tests, prior_results, effective_mode):
        """Filter out already-passed tests when running in RESUME mode.

        :param tests: List of scheduled tests.
        :param prior_results: List of prior PytestProcessInfo records.
        :param effective_mode: The resolved RunMode (CHECK has already been collapsed
            to RESUME or RESTART by :meth:`_resolve_check_mode`).
        :return: Filtered list of tests.
        """
        original_count = len(tests)
        if effective_mode == RunMode.RESUME:
            passed = {r.name for r in prior_results if r.exit_code == PyTestFlyExitCode.OK}
            tests = [t for t in tests if t.node_id not in passed]
            log.info(f"RESUME filter: {original_count} discovered, {len(passed)} passed in prior run, {len(tests)} to re-run")
        else:
            log.info(f"run_mode={effective_mode!r} (not RESUME), skipping filter — all {original_count} tests will run")
        return tests

    def _resolve_check_mode(self, prior_results) -> RunMode:
        """Collapse :attr:`RunMode.CHECK` into either RESUME or RESTART based on the PUT fingerprint.

        If the prior run's PUT fingerprint matches the current one, behave like RESUME;
        otherwise restart.  A dirty working tree always changes the fingerprint (because
        :meth:`PutVersionInfo.fingerprint` incorporates ``git_dirty``) so developers
        iterating on code get fresh runs.

        :param prior_results: Records from the most recent prior run, or an empty list.
        :return: Either :attr:`RunMode.RESUME` or :attr:`RunMode.RESTART`.
        """
        current_fp = self.put_version_info.fingerprint() if self.put_version_info else ""
        prior_fp = None
        for record in prior_results:
            if record.put_fingerprint:
                prior_fp = record.put_fingerprint
                break
        if prior_fp is None:
            log.info("CHECK: no prior PUT fingerprint recorded, restarting")
            return RunMode.RESTART
        if prior_fp != current_fp:
            log.info(f"CHECK: PUT fingerprint changed ({prior_fp!r} -> {current_fp!r}), restarting")
            return RunMode.RESTART
        log.info(f"CHECK: PUT fingerprint unchanged ({current_fp!r}), resuming")
        return RunMode.RESUME

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

    def soft_stop(self):
        """Stop scheduling new tests but let running tests finish."""
        self.pytest_runner.soft_stop()
        self._soft_stop_requested = True
        self.stop_button.setEnabled(False)

    def force_stop(self):
        """Immediately terminate all running tests."""
        self.pytest_runner.stop()
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.force_stop_button.setEnabled(False)
        self.run_guid = None
