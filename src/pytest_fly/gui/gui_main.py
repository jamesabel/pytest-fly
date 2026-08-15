"""
Main application window for pytest-fly.

Houses the tab widget, periodic refresh timer, and coordinates data flow
between the :class:`~pytest_fly.db.PytestProcessInfoDB`, the
:class:`~pytest_fly.gui.coverage_tracker.CoverageTracker`, and the individual
GUI tabs.
"""

import time
from pathlib import Path
from queue import Empty

from PySide6.QtCore import QCoreApplication, QRect, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QTabWidget,
)
from typeguard import typechecked

from ..__version__ import application_name
from ..db import PytestProcessInfoDB
from ..interfaces import PyTestFlyExitCode, PytestRunnerState
from ..logger import get_logger
from ..preferences import get_pref
from ..pytest_runner.system_monitor import SystemMonitor, SystemMonitorSample
from ..tick_data import build_tick_data
from .about_tab.about import About
from .configuration_tab.configuration import Configuration
from .coverage_tab import CoverageTab
from .coverage_tracker import CoverageTracker
from .graph_tab import GraphTab
from .gui_util import PhaseTimer, get_font, get_text_dimensions, qt_state_from_hex, qt_state_to_hex
from .run_tab import RunTab
from .table_tab import TableTab
from .target_path_dialog import ensure_valid_target_project_path

log = get_logger()


class FlyAppMainWindow(QMainWindow):
    """Top-level application window containing the six main tabs."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

        # When True, closeEvent skips the "tests are running" confirmation dialog. Set under
        # automation (screenshot capture, auto-quit-on-done) where a modal prompt would block.
        self._suppress_close_confirmation = False

        super().__init__()

        # set monospace font
        font = get_font()
        self.setFont(font)

        # ensure monospace font is used
        space_dimension = get_text_dimensions(" ")
        wide_character_dimension = get_text_dimensions("X")
        if space_dimension.width() != wide_character_dimension.width():
            log.warning(f"monospace font not used (font={font})")

        # Restore window geometry. saveGeometry/restoreGeometry round-trips the exact frame
        # position, size, and maximized/fullscreen state (and clamps to the available screens),
        # which a manual frame-rect save + setGeometry restore cannot — setGeometry sets the
        # client area while frameGeometry includes the frame, so that pairing drifted the window
        # by the frame thickness on every reopen.
        pref = get_pref()
        saved_geometry = qt_state_from_hex(pref.window_geometry)
        restored = saved_geometry is not None and self.restoreGeometry(saved_geometry)
        if not restored:
            # First run (or unreadable geometry): size to a padded fraction of the primary screen.
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            padding = 0.1  # leave a little padding on each side
            screen_width = screen_geometry.width()
            screen_height = screen_geometry.height()
            self.setGeometry(QRect(int(padding * screen_width), int(padding * screen_height), int((1.0 - 2 * padding) * screen_width), int((1.0 - 2 * padding) * screen_height)))

        self.setWindowTitle(application_name)

        icon_path = Path(__file__).parent / "icons" / "app_icon.ico"
        if icon_path.exists():
            app_icon = QIcon(str(icon_path))
            self.setWindowIcon(app_icon)
            QApplication.instance().setWindowIcon(app_icon)

        # add tab windows
        self.tab_widget = QTabWidget()
        # ensure the tab widget expands but does not force the main window to grow
        self.tab_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.run_tab = RunTab(self, self.data_dir)
        self.graph_tab = GraphTab()
        self.table_tab = TableTab(self.data_dir)
        self.coverage_tab = CoverageTab(self.data_dir)
        self.configuration = Configuration()
        self.about = About(self, self.data_dir)
        self.tab_widget.addTab(self.run_tab, "Run")
        self.tab_widget.addTab(self.graph_tab, "Graph")
        self.tab_widget.addTab(self.table_tab, "Table")
        self.tab_widget.addTab(self.coverage_tab, "Coverage")
        self.tab_widget.addTab(self.configuration, "Configuration")
        self.tab_widget.addTab(self.about, "About")

        self._coverage_tracker = CoverageTracker(self.data_dir)

        # query_last_pass scans the full DB history — cache its result and only
        # re-query when the set of passing tests in the current run has grown.
        self._last_pass_cache: dict[str, tuple[float, float]] = {}
        self._last_pass_cache_run_guid: str | None = None
        self._last_pass_cache_pass_count: int = -1

        self.table_tab.force_stop_test_requested.connect(self._force_stop_single_test)

        self.setCentralWidget(self.tab_widget)

        # System-wide performance monitor subprocess — sampled at a fixed 1 s cadence independent
        # of the GUI refresh rate, drained non-blocking on each tick.
        self._system_monitor = SystemMonitor(update_rate=1.0)
        self._system_monitor.start()

        # timer for periodic updates
        self.timer = QTimer(self, interval=int(round(pref.refresh_rate * 1000)))
        self.timer.timeout.connect(self._update_tick)
        self.timer.start()

    def reset(self):
        """Reset all tabs to their initial state."""
        self.table_tab.reset()

    def closeEvent(self, event, /):

        log.info(f"{self.__class__.__name__}.closeEvent() - entering")

        # If a run is in progress, confirm with the user before tearing it down. Skipped under
        # automation, where a modal prompt would block the programmatic close.
        pytest_runner = self.run_tab.control_window.pytest_runner
        if not self._suppress_close_confirmation and pytest_runner is not None and pytest_runner.is_running():
            response = QMessageBox.question(
                self,
                "Tests are running",
                "A test run is currently in progress. Exiting now will stop it.\n\nAre you sure you want to exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if response != QMessageBox.StandardButton.Yes:
                log.info(f"{self.__class__.__name__}.closeEvent() - cancelled by user")
                event.ignore()
                return

        pref = get_pref()

        # Save window geometry via Qt's own serialization (frame, size, and maximized state), so
        # restoreGeometry() on next launch returns to the exact prior placement. Matches the hex
        # persistence used for the Run-tab splitters.
        pref.window_geometry = qt_state_to_hex(self.saveGeometry())

        if pytest_runner is not None and pytest_runner.is_running():
            pytest_runner.stop()
            QCoreApplication.processEvents()
            pytest_runner.join(30.0)

        self._system_monitor.request_stop()
        self._system_monitor.join(5.0)

        event.accept()

    def _force_stop_single_test(self, test_name: str):
        """Handle request to terminate a single running test from the table tab.

        If no worker is currently running the test — a stale "Running" row whose process
        died without writing a terminal record, or a run that is no longer active — write
        a TERMINATED record directly so the row clears instead of showing Running forever.
        """
        control = self.run_tab.control_window
        runner = control.pytest_runner
        if runner is not None and runner.is_running() and runner.force_stop_test(test_name):
            return
        with PytestProcessInfoDB(self.data_dir) as db:
            if db.mark_test_terminated_if_stale(control.run_guid, test_name):
                log.info(f'force stop: cleared stale running row for "{test_name}"')

    def _drain_system_monitor(self) -> None:
        """Drain queued system-resource samples into the Run tab's metrics widget."""
        samples: list[SystemMonitorSample] = []
        queue = self._system_monitor.system_monitor_queue
        while True:
            try:
                samples.append(queue.get_nowait())
            except Empty:
                break
        if samples:
            self.run_tab.system_metrics_window.ingest_samples(samples)

    def _update_tick(self):
        """Timer event handler — query the DB and refresh all tabs.

        The query runs synchronously on the GUI thread (sub-millisecond for
        typical result sets).  Grouping, time-window, and run-state computation
        happen once in :func:`build_tick_data` and the resulting :class:`TickData`
        is shared across all tabs.

        Per-phase wall-clock timings are captured via :class:`PhaseTimer` and
        emitted once per tick to help diagnose UI lag.  Logged at ``info`` when
        ``pref.perf_logging`` is enabled, otherwise at ``debug``.
        """
        timer = PhaseTimer()
        tick_start = time.perf_counter()

        run_guid = self.run_tab.control_window.run_guid
        with PytestProcessInfoDB(self.data_dir) as db:
            with timer.time("db_query"):
                process_infos = db.query(run_guid)
            with timer.time("db_last_pass"):
                # query_last_pass scans the full DB — only re-run when the set of
                # passing tests for the current run has grown, or on run change.
                pass_count = sum(1 for info in process_infos if info.exit_code == PyTestFlyExitCode.OK)
                if run_guid != self._last_pass_cache_run_guid or pass_count != self._last_pass_cache_pass_count:
                    self._last_pass_cache = db.query_last_pass()
                    self._last_pass_cache_run_guid = run_guid
                    self._last_pass_cache_pass_count = pass_count
                last_pass_data = self._last_pass_cache

        control = self.run_tab.control_window
        with timer.time("build"):
            tick = build_tick_data(
                process_infos,
                prior_durations=control.prior_durations,
                num_processes=control.num_processes,
                current_run_start=control.current_run_start,
                singleton_names=control.singleton_names,
                put_version_info=control.put_version_info,
            )
            tick.last_pass_data = last_pass_data
            tick.soft_stop_requested = control._soft_stop_requested
            runner = control.pytest_runner
            if runner is not None:
                tick.stall_info = runner.get_stall_info()
                tick.resource_guard_info = runner.get_resource_guard_info()
                # When a run has finished but some tests never reached a terminal state
                # (e.g. singletons that were blocked behind a wedged slot), surface them.
                completion = runner.get_run_completion()
                if completion is not None and runner.is_user_complete():
                    _n_terminal, _n_total, stuck = completion
                    tick.run_complete_stuck = stuck

        with timer.time("cov"):
            self._coverage_tracker.handle_new_run(control.run_guid)
            self._coverage_tracker.update(tick)
            self._coverage_tracker.apply_to_tick(tick)

        with timer.time("sysmon"):
            self._drain_system_monitor()

        with timer.time("graph"):
            self.graph_tab.update_tick(tick)
        with timer.time("table"):
            self.table_tab.update_tick(tick)
        with timer.time("run"):
            self.run_tab.update_tick(tick)
        with timer.time("cov_tab"):
            self.coverage_tab.update_tick(tick)

        total_ms = (time.perf_counter() - tick_start) * 1000.0
        n_completed = sum(1 for rs in tick.run_states.values() if rs.get_state() in (PytestRunnerState.PASS, PytestRunnerState.FAIL))
        message = f"tick total={total_ms:.1f}ms {timer.format()} n_rows={len(process_infos)} n_tests={len(tick.infos_by_name)} n_completed={n_completed}"
        if get_pref().perf_logging:
            log.info(message)
        else:
            log.debug(message)


@typechecked()
def fly_main(data_dir: Path, *, auto_start: bool = False, auto_quit_on_done: bool = False):
    """
    Main function to start the GUI application.

    :param data_dir: Application data directory (DB, logs).
    :param auto_start: When True, click the Run button shortly after the window appears.
        Used by the screenshot/GIF capture script and other automation.
    :param auto_quit_on_done: When True, close the window once the active runner finishes.
        Only meaningful with ``auto_start=True`` (or some other automation that triggers a run).
    """

    app = QApplication([])
    fly_app = FlyAppMainWindow(data_dir)
    # Under automation the window may be closed programmatically while a run is active; suppress
    # the interactive "tests are running" confirmation so it doesn't block the close.
    if auto_start or auto_quit_on_done:
        fly_app._suppress_close_confirmation = True
    fly_app.show()

    # If the configured target project path is missing, guide the user to a valid one right away
    # rather than letting them discover an empty run later. Skipped under automation (auto_start),
    # where a modal would block and the path is controlled by the caller.
    if not auto_start:
        if ensure_valid_target_project_path(fly_app) is not None:
            fly_app.configuration.refresh_target_project_path()

    if auto_start:
        # Give the window one paint cycle so test discovery has a populated UI to render into.
        QTimer.singleShot(800, fly_app.run_tab.control_window.run)

    if auto_quit_on_done:
        # Poll the runner; close the window once a run has started AND finished. The runner
        # is None until the Run button is clicked. There's also a brief window after
        # PytestRunner.start() where workers haven't been spawned yet and is_running() returns
        # False — guard against that with a "saw_running" latch so we only quit after we've
        # actually observed the run executing.
        quit_timer = QTimer(fly_app, interval=500)
        state = {"saw_running": False}

        def _check_done():
            runner = fly_app.run_tab.control_window.pytest_runner
            if runner is None:
                return
            if runner.is_running():
                state["saw_running"] = True
            # Quit once a run has started and is finished. Use the terminal-state completion
            # view (Part D) in addition to thread liveness so a wedged worker can't prevent quit.
            if state["saw_running"] and (not runner.is_running() or runner.is_user_complete()):
                quit_timer.stop()
                fly_app.close()

        quit_timer.timeout.connect(_check_done)
        quit_timer.start()

    app.exec()
