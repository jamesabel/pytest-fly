"""Run tab — combines the control panel (Run/Stop buttons) with the status summary."""

from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtWidgets import QHBoxLayout, QSplitter, QVBoxLayout, QWidget
from typeguard import typechecked

from ...logger import get_logger
from ...preferences import get_pref
from ...tick_data import TickData
from .control_window import ControlWindow
from .failed_tests_window import FailedTestsWindow
from .status_window import StatusWindow
from .system_metrics_window import SystemMetricsWindow

log = get_logger()


class RunTab(QWidget):
    """Primary tab combining the control panel (Run/Stop) and the status summary."""

    @typechecked
    def __init__(self, parent, data_dir: Path):
        super().__init__(parent)

        outer_layout = QVBoxLayout()
        self.setLayout(outer_layout)

        self.control_window = ControlWindow(self, data_dir)
        self.status_window = StatusWindow(self)
        self.system_metrics_window = SystemMetricsWindow(self)
        self.failed_tests_window = FailedTestsWindow(self)

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

        # Vertical splitter: user drags the divider between the top row and the failed-tests pane.
        # State is persisted via FlyPreferences.run_tab_splitter_state (QSplitter.saveState() hex).
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(top_container)
        self.splitter.addWidget(self.failed_tests_window)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self._restore_splitter_state()
        self.splitter.splitterMoved.connect(self._on_splitter_moved)

        outer_layout.addWidget(self.splitter)

    def update_tick(self, tick: TickData):
        """Forward pre-computed tick data to the status window, failed tests pane, and control panel."""
        self.status_window.update_tick(tick)
        self.failed_tests_window.update_tick(tick)
        self.system_metrics_window.update_tick()
        self.control_window.update()

    def _restore_splitter_state(self) -> None:
        """Restore the saved splitter divider position, if any."""
        saved = get_pref().run_tab_splitter_state
        if not saved:
            return
        try:
            self.splitter.restoreState(QByteArray.fromHex(saved.encode("ascii")))
        except (ValueError, UnicodeEncodeError) as exc:
            log.debug(f"could not restore run-tab splitter state: {exc}")

    def _on_splitter_moved(self, pos: int, index: int) -> None:
        """Persist the splitter divider position so the layout restores on next launch."""
        get_pref().run_tab_splitter_state = self.splitter.saveState().toHex().data().decode("ascii")
