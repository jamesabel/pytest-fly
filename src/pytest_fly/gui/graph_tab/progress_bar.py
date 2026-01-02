import time

from typeguard import typechecked
from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter, QPen, QBrush, QPalette
import humanize

from ...interfaces import PytestProcessInfo
from ...pytest_runner.pytest_runner import PytestRunState, PytestRunnerState
from ..gui_util import get_text_dimensions
from ...logger import get_logger

log = get_logger()


class PytestProgressBar(QWidget):
    """
    A progress bar for a single test. The progress bar shows the status of the test, including the time it has been running.
    """

    @typechecked()
    def __init__(
        self,
        status_list: list[PytestProcessInfo],
        min_time_stamp: float,
        max_time_stamp: float,
    ) -> None:

        super().__init__()
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.one_character_dimensions = get_text_dimensions("X")  # using monospace characters, so this is the width of any character

        self.status_list = status_list
        self.min_time_stamp = min_time_stamp
        self.max_time_stamp = max_time_stamp

        # set height of the progress bar
        if len(status_list) > 0:
            name = status_list[0].name
            name_text_dimensions = get_text_dimensions(name)
        else:
            # generally the status_list should have at least one element, but just in case use a default
            name_text_dimensions = self.one_character_dimensions
        self.bar_margin = 1  # pixels each side
        self.bar_height = name_text_dimensions.height() + 2 * self.bar_margin  # 1 character plus padding
        self.setFixedHeight(self.bar_height)
        log.info(f"{self.bar_height=},{name_text_dimensions=}")
        self.update_pytest_process_info(status_list, min_time_stamp, max_time_stamp)

    def update_pytest_process_info(self, status_list: list[PytestProcessInfo], min_time_stamp: float, max_time_stamp: float):
        # Save the new state and request a repaint
        self.status_list = status_list
        self.min_time_stamp = min_time_stamp
        self.max_time_stamp = max_time_stamp

        # adjust height if we have a name to size against
        if len(self.status_list) > 0:
            name = self.status_list[0].name
            name_text_dimensions = get_text_dimensions(name)
        else:
            name_text_dimensions = self.one_character_dimensions
        self.bar_height = name_text_dimensions.height() + 2 * self.bar_margin
        self.setFixedHeight(self.bar_height)

        self.update()  # schedule a repaint on the GUI thread

    def paintEvent(self, event):
        # Draw based on the latest saved state
        if len(self.status_list) > 0:

            pytest_run_state = PytestRunState(self.status_list)

            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)

            if pytest_run_state.get_state() == PytestRunnerState.QUEUED:
                start_running_time = None
            else:
                start_running_time = self.status_list[1].time_stamp

            if pytest_run_state.get_state() == PytestRunnerState.RUNNING:
                end_time = time.time()
            else:
                end_time = self.status_list[-1].time_stamp

            bar_text = f"{pytest_run_state.get_name()} - {pytest_run_state.get_string()}"

            outer_rect = self.rect()
            overall_time_window = max(self.max_time_stamp - self.min_time_stamp, 1)
            horizontal_pixels_per_second = outer_rect.width() / overall_time_window

            bar_color = pytest_run_state.get_qt_color()

            if pytest_run_state.get_state() == PytestRunnerState.QUEUED:
                x1 = outer_rect.x() + self.bar_margin
                y1 = outer_rect.y() + self.bar_margin
                w = 1
                h = self.one_character_dimensions.height()
                painter.setPen(QPen(bar_color, 1))
                bar_rect = QRectF(x1, y1, w, h)
            else:
                seconds_from_start = start_running_time - self.min_time_stamp
                x1 = (seconds_from_start * horizontal_pixels_per_second) + self.bar_margin
                y1 = outer_rect.y() + self.bar_margin
                w = ((end_time - start_running_time) * horizontal_pixels_per_second) - (2 * self.bar_margin)
                h = self.one_character_dimensions.height()
                painter.setPen(QPen(bar_color, 1))
                bar_rect = QRectF(x1, y1, w, h)

            painter.fillRect(bar_rect, QBrush(bar_color))

            text_left_margin = self.one_character_dimensions.width()
            text_y_margin = int(round((0.5 * self.one_character_dimensions.height() + self.bar_margin + 1)))

            palette = self.palette()
            text_color = palette.color(QPalette.WindowText)
            painter.setPen(QPen(text_color, 1))
            painter.drawText(outer_rect.x() + text_left_margin, outer_rect.y() + text_y_margin, bar_text)

            painter.end()
        else:

            super().paintEvent(event)
