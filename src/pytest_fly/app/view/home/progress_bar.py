from typing import List, Optional
from datetime import datetime, timedelta
import math

from pytest import ExitCode
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QSizePolicy, QStatusBar, QLabel
from PySide6.QtCore import Qt, QRectF, QPointF, QRect
from PySide6.QtGui import QPainter, QColor, QPen, QPaintEvent

from ..gui_util import get_text_dimensions
from ...model import PytestStatus, PytestProcessState, exit_code_to_string
from ...logging import get_logger

log = get_logger()


class PytestProgressBar(QWidget):
    def __init__(self, status_list: list[PytestStatus], min_time_stamp: float, max_time_stamp: float, parent: QWidget) -> None:
        super().__init__(parent)
        self.min_time_stamp = min_time_stamp
        self.max_time_stamp = max_time_stamp
        self.status_list = status_list
        layout = QVBoxLayout()
        self.setLayout(layout)

        self.one_character_dimensions = get_text_dimensions("X")  # using monospace characters, so this is the width of any character

        # set height of the progress bar
        if len(status_list) > 0:
            name = status_list[0].name
            name_text_dimensions = get_text_dimensions(name)
        else:
            # generally the status_list should have at least one element, but just in case use a default
            name_text_dimensions = self.one_character_dimensions
        self.bar_margin = 1  # pixels each side
        self.bar_height = name_text_dimensions.height() + 2 * self.bar_margin  # 1 character plus padding
        log.info(f"{self.bar_height=},{name_text_dimensions=}")
        self.setFixedHeight(self.bar_height)

    def update_status(self, status_list: list[PytestStatus], min_time_stamp: float, max_time_stamp: float) -> None:
        """
        Update the status list for the progress bar. Called when the status list changes for this test.

        :param status_list: the list of statuses for this test
        :param min_time_stamp: the minimum time stamp for all tests
        :param max_time_stamp: the maximum time stamp for all tests
        """
        self.status_list = status_list
        self.update()

    def update_time_window(self, min_time_stamp: float, max_time_stamp: float) -> None:
        """
        Update the time window for the progress bar. Called when the overall time window changes, but not for this test.

        :param min_time_stamp: the minimum time stamp for all tests
        :param max_time_stamp: the maximum time stamp for all tests
        """
        self.min_time_stamp = min_time_stamp
        self.max_time_stamp = max_time_stamp
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:

        if len(self.status_list) > 0:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)

            name = self.status_list[0].name

            start_time = min([s.time_stamp for s in self.status_list])
            end_time = max([s.time_stamp for s in self.status_list])
            if len(self.status_list) > 0:
                most_recent_status = self.status_list[-1]
                most_recent_process_state = most_recent_status.state
                most_recent_exit_code = most_recent_status.exit_code
                most_recent_exit_code_string = exit_code_to_string(most_recent_exit_code)
            else:
                most_recent_process_state = PytestProcessState.UNKNOWN
                most_recent_exit_code = None
                most_recent_exit_code_string = ""

            if math.isclose(start_time, end_time):
                bar_text = f"{name} - {most_recent_process_state.name}"
            else:
                duration = end_time - start_time
                bar_text = f"{name} - {most_recent_process_state.name},{most_recent_exit_code_string} - {duration:.2f}s)"

            outer_rect = self.rect()

            if most_recent_process_state == PytestProcessState.QUEUED:
                color = Qt.black
            elif most_recent_process_state == PytestProcessState.RUNNING:
                color = Qt.blue
            elif most_recent_process_state == PytestProcessState.FINISHED:
                if most_recent_exit_code == ExitCode.OK:
                    color = Qt.green
                else:
                    color = Qt.red

            pen = QPen(color, 1)
            painter.setPen(pen)
            # painter.drawRect(outer_rect)

            # Title near the top
            text_left_margin = self.one_character_dimensions.width()
            text_y_margin = int(round((0.5 * self.one_character_dimensions.height() + self.bar_margin + 1)))
            painter.drawText(outer_rect.x() + text_left_margin, outer_rect.y() + text_y_margin, bar_text)

            overall_time_window = max(self.max_time_stamp - self.min_time_stamp, 1)  # at least 1 second
            horizontal_pixels_per_second = outer_rect.width() / overall_time_window

            # Coordinates for the horizontal bar
            x1 = int(round((start_time - self.min_time_stamp) * horizontal_pixels_per_second)) + self.bar_margin
            y1 = outer_rect.y() + self.bar_margin
            w = int(round((end_time - start_time) * horizontal_pixels_per_second)) - (2 * self.bar_margin)
            h = self.one_character_dimensions.height()
            # Draw the main horizontal bar
            painter.drawRect(x1, y1, w, h)

            painter.end()
