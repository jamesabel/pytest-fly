from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QWidget, QScrollArea
from PySide6.QtCore import Qt

from ...tick_data import TickData
from .progress_bar import PytestProgressBar
from .time_axis import TimeAxisWidget


class GraphTab(QGroupBox):
    """Tab displaying a horizontal progress bar for each test module with a shared time axis."""

    def __init__(self):
        super().__init__()
        self.setTitle("Progress")
        self.progress_bars: dict[str, PytestProgressBar] = {}

        outer_layout = QVBoxLayout()
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
        self._bar_container.setLayout(self._bar_layout)
        self._scroll_area.setWidget(self._bar_container)

    def update_tick(self, tick: TickData) -> None:
        """Refresh the time axis and all progress bars from pre-computed tick data."""

        self.time_axis.update_time_window(tick.min_time_stamp, tick.max_time_stamp)

        for test_name, infos in tick.infos_by_name.items():
            run_state = tick.run_states[test_name]
            if test_name in self.progress_bars:
                progress_bar = self.progress_bars[test_name]
                progress_bar.update_pytest_process_info(infos, tick.min_time_stamp, tick.max_time_stamp, run_state)
            else:
                progress_bar = PytestProgressBar(infos, tick.min_time_stamp, tick.max_time_stamp, run_state)
                self._bar_layout.addWidget(progress_bar)
                self.progress_bars[test_name] = progress_bar
