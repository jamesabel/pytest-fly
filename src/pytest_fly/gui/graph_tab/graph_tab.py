"""Graph tab — horizontal progress bars showing test execution timelines."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGroupBox, QScrollArea, QVBoxLayout, QWidget

from ...tick_data import TickData
from .progress_bar import PytestProgressBar
from .time_axis import TimeAxisWidget


class GraphTab(QGroupBox):
    """Tab displaying a horizontal progress bar for each test module with a shared time axis."""

    def __init__(self):
        super().__init__()
        self.setTitle("Progress")
        self.progress_bars: dict[str, PytestProgressBar] = {}
        self._layout_order: list[str] = []

        outer_layout = QVBoxLayout()
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        self.setLayout(outer_layout)

        self.time_axis = TimeAxisWidget()
        outer_layout.addWidget(self.time_axis)

        # Scroll area for the progress bars so large test suites don't blow out the tab size
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        outer_layout.addWidget(self._scroll_area, stretch=1)

        self._bar_container = QWidget()
        self._bar_layout = QVBoxLayout()
        self._bar_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        # Pack bars flush — Qt's default spacing/margins push rows apart enough
        # that only a handful fit on screen at once.
        self._bar_layout.setSpacing(0)
        self._bar_layout.setContentsMargins(0, 0, 0, 0)
        self._bar_container.setLayout(self._bar_layout)
        self._scroll_area.setWidget(self._bar_container)

    def update_tick(self, tick: TickData) -> None:
        """Refresh the time axis and all progress bars from pre-computed tick data."""

        effective_min = tick.effective_min_time_stamp

        self.time_axis.update_time_window(effective_min, tick.max_time_stamp)

        # Remove bars for tests no longer in the current tick
        removed_names = set(self.progress_bars) - set(tick.infos_by_name)
        for name in removed_names:
            bar = self.progress_bars.pop(name)
            self._bar_layout.removeWidget(bar)
            bar.deleteLater()

        # Create or update bars
        for test_name, infos in tick.infos_by_name.items():
            run_state = tick.run_states[test_name]
            is_singleton = test_name in tick.singleton_names
            if test_name in self.progress_bars:
                progress_bar = self.progress_bars[test_name]
                progress_bar.update_pytest_process_info(infos, effective_min, tick.max_time_stamp, run_state, is_singleton)
            else:
                progress_bar = PytestProgressBar(infos, effective_min, tick.max_time_stamp, run_state, is_singleton)
                self.progress_bars[test_name] = progress_bar

        # Ensure layout order matches tick.infos_by_name order (same as table tab).
        # In steady state the order doesn't change — skip the takeAt/addWidget churn
        # (and associated layout invalidation) when the order is already correct.
        desired_order = list(tick.infos_by_name)
        if desired_order != self._layout_order:
            while self._bar_layout.count():
                self._bar_layout.takeAt(0)
            for test_name in desired_order:
                self._bar_layout.addWidget(self.progress_bars[test_name])
            self._layout_order = desired_order
