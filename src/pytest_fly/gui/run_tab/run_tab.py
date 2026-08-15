"""Run tab — the control panel (Run/Stop), status summary, system metrics,
failed-tests list, and live-output pane, arranged in two persisted splitters."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QSplitter, QVBoxLayout, QWidget
from typeguard import typechecked

from ...logger import get_logger
from ...tick_data import TickData
from ..gui_util import bind_splitter_to_pref
from .control_window import ControlWindow
from .failed_tests_window import FailedTestsWindow
from .live_output_window import LiveOutputWindow
from .status_window import StatusWindow
from .system_metrics_window import SystemMetricsWindow

log = get_logger()


class RunTab(QWidget):
    """Primary tab combining the control panel (Run/Stop) and the status summary."""

    @typechecked()
    def __init__(self, parent, data_dir: Path):
        super().__init__(parent)

        outer_layout = QVBoxLayout()
        self.setLayout(outer_layout)

        self.control_window = ControlWindow(self, data_dir)
        self.status_window = StatusWindow(self)
        self.system_metrics_window = SystemMetricsWindow(self)
        self.failed_tests_window = FailedTestsWindow(self)
        self.live_output_window = LiveOutputWindow(self, data_dir)
        # Clicking a failed test pins its captured output into the Live Output pane.
        self.failed_tests_window.failed_test_selected.connect(self.live_output_window.set_pinned_failed_test)

        top_container = QWidget()
        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_container.setLayout(top_layout)
        # ControlWindow is Fixed-size and pinned to the top. StatusWindow and SystemMetricsWindow
        # fill the full vertical space of the top pane (up to the splitter divider) so the
        # status text never has to scroll.
        top_layout.addWidget(self.control_window, alignment=Qt.AlignmentFlag.AlignTop)
        top_layout.addWidget(self.status_window)
        top_layout.addWidget(self.system_metrics_window, stretch=1)

        # Bottom pane: a horizontal splitter so the user can size Failed Tests vs Live Output
        # independently of the outer top/bottom divider.
        self.bottom_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.bottom_splitter.setChildrenCollapsible(False)
        self.bottom_splitter.addWidget(self.failed_tests_window)
        self.bottom_splitter.addWidget(self.live_output_window)
        self.bottom_splitter.setStretchFactor(0, 0)
        self.bottom_splitter.setStretchFactor(1, 1)

        # Vertical splitter: user drags the divider between the top row and the bottom pane.
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(top_container)
        self.splitter.addWidget(self.bottom_splitter)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)

        # Both divider positions persist across launches (hex-encoded QSplitter.saveState()).
        bind_splitter_to_pref(self.bottom_splitter, "run_tab_bottom_splitter_state")
        bind_splitter_to_pref(self.splitter, "run_tab_splitter_state")

        outer_layout.addWidget(self.splitter)

    def update_tick(self, tick: TickData):
        """Forward pre-computed tick data to all child windows in the Run tab."""
        self.status_window.update_tick(tick)
        self.failed_tests_window.update_tick(tick)
        self.live_output_window.update_tick(tick)
        self.system_metrics_window.update_tick(tick)
        self.control_window.reconcile_process_count()
        self.control_window.refresh_button_state(tick.user_complete)
