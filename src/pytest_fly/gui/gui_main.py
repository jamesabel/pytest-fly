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
    QSizePolicy,
    QTabWidget,
)
from typeguard import typechecked

from ..__version__ import application_name
from ..db import PytestProcessInfoDB
from ..interfaces import PutVersionInfo, PytestRunnerState
from ..logger import get_logger
from ..preferences import get_pref
from ..pytest_runner.pytest_runner import PytestRunState
from ..pytest_runner.system_monitor import SystemMonitor, SystemMonitorSample
from ..tick_data import TickData
from .about_tab.about import About
from .configuration_tab.configuration import Configuration
from .coverage_tab import CoverageTab
from .coverage_tracker import CoverageTracker
from .graph_tab import GraphTab
from .gui_util import PhaseTimer, compute_average_parallelism, compute_time_window, get_font, get_text_dimensions, group_process_infos_by_name
from .run_tab import RunTab
from .table_tab import TableTab

log = get_logger()


def build_tick_data(
    process_infos: list,
    prior_durations: dict[str, float] | None = None,
    num_processes: int = 1,
    current_run_start: float | None = None,
    singleton_names: set[str] | None = None,
    put_version_info: PutVersionInfo | None = None,
) -> TickData:
    """
    Build a :class:`TickData` bundle from a flat list of process info records.

    Performs grouping, time-window computation, and run-state construction
    once so that all tabs can share the pre-computed results.

    ``infos_by_name`` and ``run_states`` are ordered alphabetically by test name
    with singleton tests last, so all tabs that iterate these dicts render in
    the same order (matching the runner's execution order).

    :param process_infos: Flat list of :class:`PytestProcessInfo` objects from the DB.
    :param prior_durations: Optional mapping of test name to prior run duration (seconds), used for ETA.
    :param num_processes: Number of parallel worker processes (used for ETA wall-clock estimation).
    :param current_run_start: Wall-clock timestamp captured when the Run button was pressed, used
        as the graph time-axis origin.  Passed in explicitly because RESUME mode copies prior-run
        records (including their original QUEUED records with ``exit_code == NONE``), so the origin
        cannot be derived reliably from DB records alone.
    :param singleton_names: Node ids of tests marked ``@pytest.mark.singleton``; these are sorted
        last in the output dicts to match the runner's end-of-queue placement.
    :return: A fully populated :class:`TickData` instance.
    """
    singletons = singleton_names if singleton_names is not None else set()
    grouped = group_process_infos_by_name(process_infos)
    ordered_names = sorted(grouped, key=lambda n: (n in singletons, n))
    infos_by_name = {name: grouped[name] for name in ordered_names}
    run_states = {name: PytestRunState(infos_by_name[name]) for name in ordered_names}
    min_ts, max_ts = compute_time_window(process_infos)
    min_ts_s, max_ts_s = compute_time_window(process_infos, require_pid=True)

    return TickData(
        process_infos=process_infos,
        infos_by_name=infos_by_name,
        run_states=run_states,
        min_time_stamp=min_ts,
        max_time_stamp=max_ts,
        min_time_stamp_started=min_ts_s,
        max_time_stamp_started=max_ts_s,
        prior_durations=prior_durations if prior_durations is not None else {},
        num_processes=num_processes,
        average_parallelism=compute_average_parallelism(infos_by_name),
        current_run_start=current_run_start,
        singleton_names=singletons,
        put_version_info=put_version_info,
    )


class FlyAppMainWindow(QMainWindow):
    """Top-level application window containing the five main tabs."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

        super().__init__()

        # set monospace font
        font = get_font()
        self.setFont(font)

        # ensure monospace font is used
        space_dimension = get_text_dimensions(" ")
        wide_character_dimension = get_text_dimensions("X")
        if space_dimension.width() != wide_character_dimension.width():
            log.warning(f"monospace font not used (font={font})")

        # restore window size and position
        pref = get_pref()
        # ensure window is not off the screen
        screen = QApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        restore_rect = QRect(int(float(pref.window_x)), int(float(pref.window_y)), int(float(pref.window_width)), int(float(pref.window_height)))
        if not screen_geometry.contains(restore_rect):
            padding = 0.1  # when resizing, leave a little padding on each side
            screen_width = screen_geometry.width()
            screen_height = screen_geometry.height()
            restore_rect = QRect(int(padding * screen_width), int(padding * screen_height), int((1.0 - 2 * padding) * screen_width), int((1.0 - 2 * padding) * screen_height))
            log.info(f"window is off the screen, moving to {restore_rect=}")
        self.setGeometry(restore_rect)

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
        self.coverage_tab = CoverageTab()
        self.configuration = Configuration()
        self.about = About(self)
        self.tab_widget.addTab(self.run_tab, "Run")
        self.tab_widget.addTab(self.graph_tab, "Graph")
        self.tab_widget.addTab(self.table_tab, "Table")
        self.tab_widget.addTab(self.coverage_tab, "Coverage")
        self.tab_widget.addTab(self.configuration, "Configuration")
        self.tab_widget.addTab(self.about, "About")

        self._coverage_tracker = CoverageTracker(self.data_dir)

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

        log.info(f"{__class__.__name__}.closeEvent() - entering")

        pref = get_pref()

        # save window size and position using frameGeometry (includes window frame)
        frame = self.frameGeometry()
        pref.window_x = frame.x()
        pref.window_y = frame.y()
        pref.window_width = frame.width()
        pref.window_height = frame.height()

        if (pytest_runner := self.run_tab.control_window.pytest_runner) is not None and pytest_runner.is_running():
            pytest_runner.stop()
            QCoreApplication.processEvents()
            pytest_runner.join(30.0)

        self._system_monitor.request_stop()
        self._system_monitor.join(5.0)

        event.accept()

    def _force_stop_single_test(self, test_name: str):
        """Handle request to terminate a single running test from the table tab."""
        control = self.run_tab.control_window
        if control.pytest_runner is not None and control.pytest_runner.is_running():
            control.pytest_runner.force_stop_test(test_name)

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

        with PytestProcessInfoDB(self.data_dir) as db:
            with timer.time("db_query"):
                process_infos = db.query(self.run_tab.control_window.run_guid)
            with timer.time("db_last_pass"):
                last_pass_data = db.query_last_pass()

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
def fly_main(data_dir: Path):
    """
    Main function to start the GUI application.
    """

    app = QApplication([])
    fly_app = FlyAppMainWindow(data_dir)
    fly_app.show()
    app.exec()
