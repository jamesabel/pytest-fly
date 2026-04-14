# python
import time
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow,
    QApplication,
    QTabWidget,
    QScrollArea,
    QSizePolicy,
)
from PySide6.QtCore import QCoreApplication, QRect, QTimer
from typeguard import typechecked

from ..db import PytestProcessInfoDB
from ..logger import get_logger
from ..gui.configuration_tab.configuration import Configuration
from ..gui.about_tab.about import About
from ..preferences import get_pref
from ..__version__ import application_name
from ..tick_data import TickData
from ..interfaces import PytestRunnerState
from ..pytest_runner.pytest_runner import PytestRunState
from ..pytest_runner.coverage import calculate_coverage
from .gui_util import get_font, get_text_dimensions, group_process_infos_by_name, compute_time_window
from .run_tab import RunTab
from .table_tab import TableTab
from .graph_tab import GraphTab
from .coverage_tab import CoverageTab


log = get_logger()


def build_tick_data(process_infos, prior_durations=None, num_processes=1):
    """
    Build a :class:`TickData` bundle from a flat list of process info records.

    Performs grouping, time-window computation, and run-state construction
    once so that all tabs can share the pre-computed results.
    """
    infos_by_name = group_process_infos_by_name(process_infos)
    run_states = {name: PytestRunState(infos) for name, infos in infos_by_name.items()}
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

        # add tab windows
        self.tab_widget = QTabWidget()
        # ensure the tab widget expands but does not force the main window to grow
        self.tab_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.run_tab = RunTab(self, self.data_dir)
        self.graph_tab = GraphTab()
        self.table_tab = TableTab()
        self.coverage_tab = CoverageTab()
        self.configuration = Configuration()
        self.about = About(self)
        self.tab_widget.addTab(self.run_tab, "Run")
        self.tab_widget.addTab(self.graph_tab, "Graph")
        self.tab_widget.addTab(self.table_tab, "Table")
        self.tab_widget.addTab(self.coverage_tab, "Coverage")
        self.tab_widget.addTab(self.configuration, "Configuration")
        self.tab_widget.addTab(self.about, "About")

        # Coverage tracking state
        self._completed_tests: set[str] = set()
        self._coverage_history: list[tuple[float, float]] = []
        self._last_run_guid: str | None = None

        # Wrap the tab widget in a scroll area so that very tall tab contents produce scrollbars
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        # QScrollArea takes ownership / reparents the widget
        self.scroll_area.setWidget(self.tab_widget)

        self.setCentralWidget(self.scroll_area)

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

        event.accept()

    def _update_tick(self):
        """
        Timer event handler — query the DB and refresh all tabs.

        The query runs synchronously on the GUI thread (sub-millisecond for
        typical result sets).  Grouping, time-window, and run-state computation
        happen once in :func:`build_tick_data` and the resulting :class:`TickData`
        is shared across all tabs.
        """
        with PytestProcessInfoDB(self.data_dir) as db:
            process_infos = db.query(self.run_tab.control_window.run_guid)

        control = self.run_tab.control_window
        tick = build_tick_data(process_infos, prior_durations=control.prior_durations, num_processes=control.num_processes)

        # Reset coverage state when a new run starts
        current_guid = control.run_guid
        if current_guid != self._last_run_guid:
            self._last_run_guid = current_guid
            self._completed_tests = set()
            self._coverage_history = []

        # Trigger coverage recalculation when new tests complete
        current_completed = {name for name, rs in tick.run_states.items() if rs.get_state() in (PytestRunnerState.PASS, PytestRunnerState.FAIL)}
        if current_completed and current_completed != self._completed_tests:
            self._completed_tests = current_completed
            try:
                coverage_pct = calculate_coverage("current", self.data_dir, write_report=False)
                if coverage_pct is not None:
                    self._coverage_history.append((time.time(), coverage_pct))
            except Exception as e:
                log.warning(f"coverage calculation failed: {e}")
        tick.coverage_history = self._coverage_history

        self.graph_tab.update_tick(tick)
        self.table_tab.update_tick(tick)
        self.run_tab.update_tick(tick)
        self.coverage_tab.update_tick(tick)


@typechecked()
def fly_main(data_dir: Path):
    """
    Main function to start the GUI application.
    """

    app = QApplication([])
    fly_app = FlyAppMainWindow(data_dir)
    fly_app.show()
    app.exec()
