from PySide6.QtWidgets import QGroupBox, QVBoxLayout
from PySide6.QtCore import Qt
from typeguard import typechecked

from ...interfaces import PytestProcessInfo
from ..gui_util import group_process_infos_by_name, compute_time_window
from .progress_bar import PytestProgressBar


class GraphTab(QGroupBox):
    """Tab displaying a horizontal progress bar for each test module."""

    def __init__(self):
        super().__init__()
        self.setTitle("Progress")
        self.progress_bars: dict[str, PytestProgressBar] = {}
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setLayout(layout)

    @typechecked()
    def update_pytest_process_info(self, pytest_process_infos: list[PytestProcessInfo]) -> None:
        """Refresh all progress bars with the latest process info records."""

        infos_by_name = group_process_infos_by_name(pytest_process_infos)
        min_time_stamp, max_time_stamp = compute_time_window(pytest_process_infos)

        layout = self.layout()

        for test_name, infos in infos_by_name.items():
            if test_name in self.progress_bars:
                progress_bar = self.progress_bars[test_name]
                progress_bar.update_pytest_process_info(infos, min_time_stamp, max_time_stamp)
            else:
                progress_bar = PytestProgressBar(infos, min_time_stamp, max_time_stamp)
                layout.addWidget(progress_bar)
                self.progress_bars[test_name] = progress_bar
