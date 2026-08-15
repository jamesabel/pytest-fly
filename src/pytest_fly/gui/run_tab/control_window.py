"""
Control window — Run/Stop buttons and parallelism/run-mode selectors.

Houses the run-preparation logic: test discovery, RESUME filtering, and
the user-configured ordering-aspect chain (see :mod:`pytest_runner.ordering`).

Run preparation is slow — git-based PUT detection, winding down a prior runner,
``pytest --collect-only`` discovery, DB reads, RESUME record copying — so it runs
on a background thread (:meth:`ControlWindow._prepare_run`); the Run click only
validates, disables the controls, and hands off.  The prepared
:class:`PytestRunner` is adopted back on the GUI thread via a queued signal.
"""

import shutil
import sqlite3
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import Event, Thread

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGroupBox, QSizePolicy, QVBoxLayout
from typeguard import typechecked

from ...db import PytestProcessInfoDB, PytestProcessInfoReader
from ...guid import generate_uuid
from ...interfaces import OrderingAspect, PutVersionInfo, PyTestFlyExitCode, RunMode, ScheduledTest
from ...logger import get_logger
from ...preferences import ParallelismControl, duration_to_seconds, get_ordering_aspects_ordered, get_pref
from ...put_version import detect_put_version
from ...pytest_runner.admission import AdmissionGateConfig
from ...pytest_runner.coverage import compute_per_test_coverage
from ...pytest_runner.ordering import OrderingContext, apply_ordering_aspects
from ...pytest_runner.pytest_runner import PytestRunner
from ...pytest_runner.resource_guard import ResourceGuardConfig
from ...pytest_runner.stall_watchdog import StallConfig
from ...pytest_runner.test_list import GetTests
from ..target_path_dialog import ensure_valid_target_project_path
from .control_pushbutton import ControlButton
from .parallelism_control_box import ParallelismControlBox
from .run_mode_control_box import RunModeControlBox

log = get_logger()


@dataclass(frozen=True)
class _RunPrepConfig:
    """Everything run preparation needs, gathered on the GUI thread at Run-click time.

    The background prep thread works only from this snapshot (plus the data dir), so it
    never touches preferences or Qt.
    """

    project_root: Path
    run_guid: str
    refresh_rate: float
    run_mode: RunMode
    processes: int
    enabled_aspects: list[OrderingAspect]
    gate_config: AdmissionGateConfig
    stall_config: StallConfig
    resource_guard_config: ResourceGuardConfig


@dataclass
class _RunPrepResult:
    """Outcome of background run preparation, adopted on the GUI thread."""

    runner: PytestRunner
    prior_durations: dict[str, float] = field(default_factory=dict)
    num_processes: int = 1
    singleton_names: set[str] = field(default_factory=set)
    put_version_info: PutVersionInfo | None = None


class ControlWindow(QGroupBox):
    """Run/Stop controls and parallelism/run-mode selectors for the Run tab."""

    # Emitted by the background prep thread when preparation finishes (payload:
    # _RunPrepResult, or None on abort/failure). Cross-thread, so Qt queues the
    # delivery onto the GUI thread.
    run_prep_finished = Signal(object)

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
        self.run_button.setToolTip("Discover tests and start a new test run")
        layout.addWidget(self.run_button)
        self.run_button.clicked.connect(self.run)

        self.stop_button = ControlButton(self, "Stop", False)
        self.stop_button.setToolTip("Wait for the running tests and then stop")
        layout.addWidget(self.stop_button)
        self.stop_button.clicked.connect(self._on_stop_clicked)

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
        self._run_prep_thread: Thread | None = None
        self._run_prep_abort = Event()
        self._run_prep_active: bool = False
        self.run_prep_finished.connect(self._on_run_prep_finished)
        # Restore the most recent run's start so the Progress Graph keeps its time-axis origin
        # after an app restart — RESUME-carried records (with genuine historical timestamps) are
        # shifted onto this origin at render time in build_tick_data.
        restored_run_start = get_pref().last_run_start
        self.current_run_start: float | None = restored_run_start if restored_run_start > 0.0 else None
        self.singleton_names: set[str] = set()
        self.put_version_info: PutVersionInfo | None = None

        self.set_fixed_width()  # calculate and set the widget width

    def set_fixed_width(self):
        """Calculate and set a fixed width based on the widest child widget."""
        # Measure the stop button at its widest label so relabeling it "Cancel Stop"
        # while a soft stop is pending does not reflow the panel.
        original_stop_text = self.stop_button.text()
        self.stop_button.setText("Cancel Stop")
        stop_width = self.stop_button.sizeHint().width()
        self.stop_button.setText(original_stop_text)
        max_width = max(self.run_button.sizeHint().width(), stop_width, self.force_stop_button.sizeHint().width(), self.parallelism_box.sizeHint().width())
        # Add some padding
        max_width += 30
        self.setFixedWidth(max_width)

    def _desired_process_count(self) -> int:
        """Number of worker processes the current preferences call for.

        Serial mode pins this to 1; parallel mode uses the configured Processes count.
        Read live from preferences so a change in the Configuration tab (or the
        parallelism selector) is reflected without restarting the run.
        """
        pref = get_pref()
        return 1 if pref.parallelism == ParallelismControl.SERIAL else pref.processes

    def reconcile_process_count(self):
        """Push the live Processes preference into the active runner, mid-run.

        Called every GUI tick so a change to the Processes count (or the parallelism
        selector) is incorporated into the running scheduler — growing or shrinking
        the worker pool — without requiring the user to restart the run.
        """
        # Keep the "Parallel (N)" label in sync with the live preference, even when idle.
        self.parallelism_box.refresh_label()

        if self.pytest_runner is None or not self.pytest_runner.is_running():
            return
        desired = self._desired_process_count()
        if desired != self.num_processes:
            self.num_processes = desired
            self.pytest_runner.set_number_of_processes(desired)

    def refresh_button_state(self, user_complete: bool | None = None):
        """Enable/disable run, stop, and force stop buttons based on the runner state.

        Named to avoid shadowing :meth:`QWidget.update`, which Qt internals may
        call to schedule a repaint — when that was overridden, a repaint request
        would silently mutate button state instead.

        :param user_complete: Part D completion already derived from this tick's records
            (:attr:`TickData.user_complete`).  ``None`` (legacy callers / no runner) falls
            back to querying the runner directly.
        """
        # While run preparation is in flight on the background thread, hold every control
        # disabled — self.pytest_runner still points at the *previous* runner (or None), so
        # the logic below would re-enable Run mid-preparation.
        if self._run_prep_active:
            self.run_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            self.force_stop_button.setEnabled(False)
            return
        runner = self.pytest_runner
        # A soft stop can originate outside this window (the resource guard's automatic
        # low-resource stop); adopt it so the Stop button relabels to Cancel Stop and the
        # status pane shows the stopping state.
        if runner is not None and runner.is_running() and not self._soft_stop_requested and runner.is_soft_stop_pending():
            self._soft_stop_requested = True
        if user_complete is None:
            user_complete = runner is not None and runner.is_user_complete()
        # Part D: gate Run on terminal-state completion (or force-stop), not pure thread
        # liveness — so a wedged worker thread can never permanently disable Run. A run is
        # "done" for the user when every test reached a terminal state or it was force-stopped.
        if runner is None or user_complete or not runner.is_running():
            self.run_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.force_stop_button.setEnabled(False)
            self._soft_stop_requested = False
        elif self._soft_stop_requested:
            # Soft stop pending: the stop button stays enabled, relabeled "Cancel Stop".
            self.run_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.force_stop_button.setEnabled(True)
        else:
            self.run_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.force_stop_button.setEnabled(True)
        self._update_stop_button_label()

    def _update_stop_button_label(self):
        """Relabel the Stop button as Cancel Stop while a soft stop is pending."""
        if self._soft_stop_requested:
            self.stop_button.setText("Cancel Stop")
            self.stop_button.setToolTip("Cancel the pending stop and keep running the queued tests")
        else:
            self.stop_button.setText("Stop")
            self.stop_button.setToolTip("Wait for the running tests and then stop")

    def run(self):
        """Validate, then prepare and launch a new run on a background thread.

        Everything that can block — git-based PUT detection, winding down a prior
        runner, ``pytest --collect-only`` discovery, DB reads, RESUME copying,
        ordering — runs in :meth:`_prepare_run` on a worker thread so the GUI stays
        responsive.  The prepared :class:`PytestRunner` is adopted back on the GUI
        thread in :meth:`_on_run_prep_finished`.
        """
        if self._run_prep_active:
            return  # a preparation is already in flight

        # Resolve the configured PUT for test discovery and PUT-version detection. If it points at
        # a directory that no longer exists, guide the user to a valid one before discovering;
        # abort the run if they cancel rather than collecting from a missing path.
        project_root = ensure_valid_target_project_path(self)
        if project_root is None:
            log.info("Run aborted: target project path is not set to an existing directory.")
            return

        # Disable the controls immediately.  Previously this happened at the END of the
        # (synchronous) preparation, so a second click during discovery re-entered run().
        self._run_prep_active = True
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.force_stop_button.setEnabled(False)

        pref = get_pref()
        self.run_guid = generate_uuid()
        # Capture start time before any prior records are copied so the graph
        # time axis can use it as the origin, rather than trying to infer it
        # from DB records (copied RESUME records also have exit_code == NONE,
        # which made the DB-derived origin fall back to a prior-run timestamp).
        self.current_run_start = time.time()
        # Persist so the graph time-axis origin survives an app restart (see __init__).
        pref.last_run_start = self.current_run_start

        # Snapshot everything preparation needs while still on the GUI thread — the
        # prep thread must not touch preferences or Qt.
        config = _RunPrepConfig(
            project_root=project_root,
            run_guid=self.run_guid,
            refresh_rate=pref.refresh_rate,
            run_mode=pref.run_mode,
            processes=self._desired_process_count(),
            enabled_aspects=get_ordering_aspects_ordered(),
            gate_config=AdmissionGateConfig(
                process_count_gate_enabled=pref.process_count_gate_enabled,
                max_descendant_processes=pref.max_descendant_processes,
                commit_gate_enabled=pref.commit_gate_enabled,
                commit_gate_threshold=pref.commit_gate_threshold,
                cpu_gate_enabled=pref.cpu_gate_enabled,
                cpu_gate_threshold=pref.cpu_gate_threshold,
            ),
            stall_config=StallConfig(
                enabled=pref.stall_detection_enabled,
                warn_seconds=duration_to_seconds(pref.stall_warn_value, pref.stall_warn_unit),
                cpu_active_epsilon=pref.cpu_active_epsilon,
                auto_force_stop=pref.auto_force_stop_on_stall,
                kill_seconds=duration_to_seconds(pref.stall_kill_value, pref.stall_kill_unit),
            ),
            resource_guard_config=ResourceGuardConfig(
                enabled=pref.resource_guard_enabled,
                min_free_disk_gb=pref.resource_guard_min_free_disk_gb,
                commit_threshold=pref.resource_guard_commit_threshold,
            ),
        )
        self._run_prep_abort.clear()
        self._run_prep_thread = Thread(target=self._prepare_run, args=(config, self.pytest_runner), name="run_prep", daemon=True)
        self._run_prep_thread.start()

    def is_run_preparation_active(self) -> bool:
        """Return ``True`` while run preparation is in flight on the background thread."""
        return self._run_prep_active

    def abort_run_preparation(self, timeout: float = 10.0) -> None:
        """Abort an in-flight run preparation and wait briefly for the prep thread to exit.

        Used by the main window's ``closeEvent`` so preparation cannot start a runner
        after the window is gone.
        """
        thread = self._run_prep_thread
        if thread is None or not thread.is_alive():
            return
        self._run_prep_abort.set()
        thread.join(timeout)

    def wait_for_run_preparation(self, timeout: float = 120.0) -> bool:
        """Block until the prep thread exits (test/automation helper; the GUI never calls this).

        Note: the adoption of the prepared runner still requires the Qt event loop to
        deliver :attr:`run_prep_finished`.

        :return: ``True`` if preparation finished within the timeout (or none was active).
        """
        thread = self._run_prep_thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def _prepare_run(self, config: _RunPrepConfig, prior_runner: PytestRunner | None) -> None:
        """Background thread body: build and start the runner, then hand it to the GUI thread.

        The ``finally`` guarantees the finished signal is emitted even if preparation
        raises, so the GUI always recovers its controls instead of staying disabled.
        """
        result: _RunPrepResult | None = None
        try:
            result = self._build_runner(config, prior_runner)
        except (OSError, RuntimeError, ValueError, sqlite3.OperationalError) as e:
            log.error(f"run preparation failed: {e}", exc_info=True)
        finally:
            self.run_prep_finished.emit(result)

    def _build_runner(self, config: _RunPrepConfig, prior_runner: PytestRunner | None) -> "_RunPrepResult | None":
        """Prepare a run: discovery, RESUME handling, ordering — and start the runner.

        Runs on the prep thread.  Returns ``None`` if aborted (the runner, if it was
        already started, is stopped again).
        """
        put_version_info = detect_put_version(config.project_root)
        log.info(f"PUT detected: {put_version_info}")

        get_tests = GetTests(test_dir=config.project_root)
        get_tests.start()

        # Wind down any previous runner while discovery proceeds. Bounded join: a wedged
        # worker thread must not hang preparation forever (and since this is no longer on
        # the GUI thread, it cannot freeze the UI either way).
        if prior_runner is not None and prior_runner.is_running():
            prior_runner.stop()
            if not prior_runner.join(120.0):
                log.warning(f"previous run did not wind down within 120 s; starting the new run anyway ({config.run_guid=})")

        while get_tests.is_alive():
            get_tests.join(1.0)
            if self._run_prep_abort.is_set():
                get_tests.terminate()
                get_tests.join(5.0)
                return None
        get_tests.join()

        tests = get_tests.get_tests()

        # Query prior results once (used by RESUME filtering, failed-first ordering, and
        # never-run prioritization). Read-only access; outputs are included because RESUME
        # mode copies these records — output and all — into the new run below.
        with PytestProcessInfoReader(self.data_dir) as db:
            prior_results = db.query(include_output=True)  # most recent run
            last_pass_data = db.query_last_pass()  # most recent passing run per test
            ever_run = db.query_ever_run_names()  # names of tests that have ever run (any PUT version)

        # CHECK mode: behave like RESUME if the PUT fingerprint matches the prior run, else RESTART.
        effective_mode = config.run_mode
        if config.run_mode == RunMode.CHECK:
            effective_mode = self._resolve_check_mode(prior_results, put_version_info)

        # Clear stale coverage data before any PytestProcess starts writing into
        # coverage/. Done here (before pytest_runner.start) rather than from a periodic
        # GUI tick so we cannot delete the directory while a still-running PytestProcess
        # is mid-coverage.save().
        if effective_mode != RunMode.RESUME:
            coverage_dir = Path(self.data_dir, "coverage")
            if coverage_dir.exists():
                shutil.rmtree(coverage_dir, ignore_errors=True)

        all_node_ids = {t.node_id for t in tests}
        tests = self._filter_for_resume(tests, prior_results, effective_mode)

        # In RESUME mode (or CHECK-as-RESUME), copy the complete prior-run records for
        # previously-passed tests into the current run so they appear in all GUI tabs
        # (table, graph, status) with their original data (runtime, CPU, memory, output, etc.).
        # The copies retain their genuine historical timestamps so query_last_pass — and thus
        # the table's "Last Pass Start" column — reports real wall-clock times.  The Progress
        # Graph, which uses current_run_start as its time-axis origin, shifts these carried-over
        # records onto the current timeline at render time (see build_tick_data); the DB is left
        # truthful rather than rewritten with synthetic timestamps.
        if effective_mode == RunMode.RESUME:
            skipped_node_ids = all_node_ids - {t.node_id for t in tests}
            if skipped_node_ids:
                prior_by_name: dict[str, list] = {}
                for r in prior_results:
                    prior_by_name.setdefault(r.name, []).append(r)
                records_to_copy = [rec for nid in sorted(skipped_node_ids) for rec in prior_by_name.get(nid, [])]
                if records_to_copy:
                    with PytestProcessInfoDB(self.data_dir) as db:
                        for record in records_to_copy:
                            db.write(replace(record, run_guid=config.run_guid))

        # Use last-pass durations for ETA estimation (from the most recent passing run)
        prior_durations = {name: duration for name, (_unused_start, duration) in last_pass_data.items()}

        # Apply the user's ordered list of ordering aspects (see Configuration tab).
        # Prior-run data still informs execution *order* even in RESTART mode — RESTART only
        # means "rerun every test," not "forget the durations/failures we know about."
        per_test_cov: dict[str, float] = {}
        if OrderingAspect.COVERAGE_EFFICIENCY in config.enabled_aspects:
            per_test_cov = compute_per_test_coverage(self.data_dir, [t.node_id for t in tests])
            # Coverage-efficiency reads duration/coverage off the ScheduledTest
            # itself, so rebuild the list with those fields populated.
            tests = [
                ScheduledTest(
                    node_id=t.node_id,
                    singleton=t.singleton,
                    duration=prior_durations.get(t.node_id),
                    coverage=per_test_cov.get(t.node_id),
                )
                for t in tests
            ]

        failed_names: set[str] = set()
        if prior_results:
            passed = {r.name for r in prior_results if r.exit_code == PyTestFlyExitCode.OK}
            failed_names = {r.name for r in prior_results} - passed

        ctx = OrderingContext(
            failed_names=failed_names,
            ever_run_names=ever_run,
            prior_durations=prior_durations,
            per_test_coverage=per_test_cov,
        )
        tests = apply_ordering_aspects(tests, config.enabled_aspects, ctx)

        if self._run_prep_abort.is_set():
            return None

        put_label = put_version_info.short_label() if put_version_info else ""
        put_fp = put_version_info.fingerprint() if put_version_info else ""
        runner = PytestRunner(
            config.run_guid,
            tests,
            config.processes,
            self.data_dir,
            config.refresh_rate,
            put_version=put_label,
            put_fingerprint=put_fp,
            gate_config=config.gate_config,
            stall_config=config.stall_config,
            resource_guard_config=config.resource_guard_config,
        )
        runner.start()

        if self._run_prep_abort.is_set():
            # Aborted between start and adoption (window closing) — stop the runner here,
            # since no GUI slot will adopt (and later stop) it.
            runner.stop()
            return None

        return _RunPrepResult(
            runner=runner,
            prior_durations=prior_durations,
            num_processes=config.processes,
            singleton_names={t.node_id for t in tests if t.singleton},
            put_version_info=put_version_info,
        )

    def _on_run_prep_finished(self, result: "_RunPrepResult | None") -> None:
        """Adopt the prepared runner (GUI thread; queued from the prep thread)."""
        self._run_prep_thread = None
        self._run_prep_active = False
        if result is None:
            log.warning("run preparation did not produce a runner (aborted or failed); controls re-enabled")
            self.run_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.force_stop_button.setEnabled(False)
            return
        self.pytest_runner = result.runner
        self.prior_durations = result.prior_durations
        self.num_processes = result.num_processes
        self.singleton_names = result.singleton_names
        self.put_version_info = result.put_version_info

        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.force_stop_button.setEnabled(True)
        self._soft_stop_requested = False
        self._update_stop_button_label()

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

    def _resolve_check_mode(self, prior_results, put_version_info: PutVersionInfo | None = None) -> RunMode:
        """Collapse :attr:`RunMode.CHECK` into either RESUME or RESTART based on the PUT fingerprint.

        If the prior run's PUT fingerprint matches the current one, behave like RESUME;
        otherwise restart.  A dirty working tree always changes the fingerprint (because
        :meth:`PutVersionInfo.fingerprint` incorporates ``git_dirty``) so developers
        iterating on code get fresh runs.

        :param prior_results: Records from the most recent prior run, or an empty list.
        :param put_version_info: PUT metadata for the run being prepared; ``None`` falls back
            to :attr:`put_version_info` (the last adopted run's).
        :return: Either :attr:`RunMode.RESUME` or :attr:`RunMode.RESTART`.
        """
        if put_version_info is None:
            put_version_info = self.put_version_info
        current_fp = put_version_info.fingerprint() if put_version_info else ""
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

    def _on_stop_clicked(self):
        """Stop-button dispatcher — request a soft stop, or cancel the pending one."""
        if self._soft_stop_requested:
            self.cancel_soft_stop()
        else:
            self.soft_stop()

    def soft_stop(self):
        """Stop scheduling new tests but let running tests finish. Cancelable until the run winds down."""
        if self.pytest_runner is None:
            return
        self.pytest_runner.soft_stop()
        self._soft_stop_requested = True
        self._update_stop_button_label()

    def cancel_soft_stop(self):
        """Cancel a pending soft stop so the remaining queued tests keep running.

        If the runner reports it is too late (the run already wound down), the pending
        flag is left set and the next :meth:`refresh_button_state` tick settles the UI.
        """
        if self.pytest_runner is not None and self.pytest_runner.cancel_soft_stop():
            self._soft_stop_requested = False
        self._update_stop_button_label()

    def force_stop(self):
        """Force-stop & reset: terminate all running tests and mark the run complete (Part B/D).

        Routes through :meth:`PytestRunner.force_stop_and_reset` so a wedged run is fully
        recovered — in-flight process trees are killed (unblocking wedged workers), remaining
        non-terminal tests are written STOPPED, and the run reports done so Run re-enables.
        """
        if self.pytest_runner is not None:
            self.pytest_runner.force_stop_and_reset()
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.force_stop_button.setEnabled(False)
        self._soft_stop_requested = False
        self._update_stop_button_label()
        self.run_guid = None
