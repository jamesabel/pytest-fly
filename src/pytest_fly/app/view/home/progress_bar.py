from typing import List, Optional
from datetime import datetime, timedelta
import math
import time

from typeguard import typechecked
from pytest import ExitCode
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QSizePolicy, QStatusBar, QLabel
from PySide6.QtCore import Qt, QRectF, QPointF, QRect
from PySide6.QtGui import QPainter, QColor, QPen, QPaintEvent, QBrush, QPalette
import humanize

from ...model import PytestProcessState, PytestProcessInfo, exit_code_to_string, state_order
from ..gui_util import get_text_dimensions
from ...logger import get_logger

log = get_logger()


class PytestProgressBar(QWidget):
    """
    A progress bar for a single test. The progress bar shows the status of the test, including the time it has been running.
    """

    @typechecked()
    def __init__(self, status_list: list[PytestProcessInfo], min_time_stamp: float, max_time_stamp: float, parent: QWidget) -> None:
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

    @typechecked()
    def update_status(self, status_list: list[PytestProcessInfo]) -> None:
        """
        Update the status list for the progress bar. Called when the status list changes for this test.

        :param status_list: the list of statuses for this test
        """
        self.status_list = status_list
        self.update()

    @typechecked()
    def update_time_window(self, min_time_stamp: float, max_time_stamp: float) -> None:
        """
        Update the time window for the progress bar. Can be called when the overall time window changes, but not for this test.

        :param min_time_stamp: the minimum time stamp for all tests
        :param max_time_stamp: the maximum time stamp for all tests
        """
        if min_time_stamp != self.min_time_stamp or max_time_stamp != self.max_time_stamp:
            self.min_time_stamp = min_time_stamp
            self.max_time_stamp = max_time_stamp
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:

        if len(self.status_list) > 0:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)

            status_list = sorted(self.status_list, key=lambda s: (state_order(s.state), s.time_stamp))

            name = status_list[0].name  # all should be the same name

            # get start of bar
            start_running_time = None
            for status in status_list:
                if status.start is not None:
                    start_running_time = status.start
                    break
            if start_running_time is None:
                for status in status_list:
                    if status.state == PytestProcessState.RUNNING:
                        start_running_time = status.time_stamp
                        break
            if start_running_time is None:
                start_running_time = status_list[-1].time_stamp

            # get end of bar
            if (end_time := status_list[-1].end) is None:
                if status_list[-1].state == PytestProcessState.QUEUED:
                    end_time = status_list[-1].time_stamp  # use the latest time stamp
                else:
                    end_time = time.time()

            most_recent_status = status_list[-1]
            most_recent_process_state = most_recent_status.state
            most_recent_exit_code = most_recent_status.exit_code
            most_recent_exit_code_string = exit_code_to_string(most_recent_exit_code)

            if end_time is None or math.isclose(start_running_time, end_time):
                bar_text = f"{name} - {most_recent_process_state}"
            else:
                duration = end_time - start_running_time
                duration_string = humanize.precisedelta(timedelta(seconds=duration))
                if most_recent_exit_code is None:
                    bar_text = f"{name} - {most_recent_process_state} ({duration_string})"
                else:
                    bar_text = f"{name} - {most_recent_process_state},{most_recent_exit_code_string} ({duration_string})"

            outer_rect = self.rect()
            overall_time_window = max(self.max_time_stamp - self.min_time_stamp, time.time() - self.min_time_stamp, 1)  # at least 1 second
            horizontal_pixels_per_second = outer_rect.width() / overall_time_window

            # determine the horizontal bar color
            bar_color = Qt.lightGray
            if most_recent_process_state == PytestProcessState.FINISHED:
                if most_recent_exit_code == ExitCode.OK:
                    bar_color = Qt.green
                else:
                    bar_color = Qt.red

            # draw the horizontal bar
            if start_running_time is None:
                # tick for the queue time
                x1 = outer_rect.x() + self.bar_margin
                y1 = outer_rect.y() + self.bar_margin
                if end_time is None:
                    w = 1
                else:
                    w = (end_time - self.min_time_stamp) * horizontal_pixels_per_second
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
            bar_brush = QBrush(bar_color)
            painter.fillRect(bar_rect, bar_brush)

            # draw the text
            text_left_margin = self.one_character_dimensions.width()
            text_y_margin = int(round((0.5 * self.one_character_dimensions.height() + self.bar_margin + 1)))

            # Set pen color based on the current palette
            palette = self.palette()
            text_color = palette.color(QPalette.WindowText)
            painter.setPen(QPen(text_color, 1))

            painter.drawText(outer_rect.x() + text_left_margin, outer_rect.y() + text_y_margin, bar_text)

            painter.end()
