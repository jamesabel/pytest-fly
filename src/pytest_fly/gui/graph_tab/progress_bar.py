from PySide6.QtWidgets import QWidget, QVBoxLayout, QToolTip
from PySide6.QtCore import QRectF, QPointF
from PySide6.QtGui import QPainter, QPen, QBrush, QPalette
import time
from typeguard import typechecked
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
        self.one_character_dimensions = get_text_dimensions("X")

        self.status_list = status_list
        self.min_time_stamp = min_time_stamp
        self.max_time_stamp = max_time_stamp

        if len(status_list) > 0:
            name = status_list[0].name
            name_text_dimensions = get_text_dimensions(name)
        else:
            name_text_dimensions = self.one_character_dimensions
        self.bar_margin = 1
        self.bar_height = name_text_dimensions.height() + 2 * self.bar_margin
        self.setFixedHeight(self.bar_height)
        log.info(f"{self.bar_height=},{name_text_dimensions=}")
        self.update_pytest_process_info(status_list, min_time_stamp, max_time_stamp)

        # --- Tooltip-related state ---
        self.setMouseTracking(True)  # receive mouseMoveEvent even with no button pressed
        self._last_bar_rect: QRectF | None = None
        self._last_bar_text: str = ""

    def update_pytest_process_info(self, status_list: list[PytestProcessInfo], min_time_stamp: float, max_time_stamp: float):
        self.status_list = status_list
        self.min_time_stamp = min_time_stamp
        self.max_time_stamp = max_time_stamp

        if len(self.status_list) > 0:
            name = self.status_list[0].name
            name_text_dimensions = get_text_dimensions(name)
        else:
            name_text_dimensions = self.one_character_dimensions
        self.bar_height = name_text_dimensions.height() + 2 * self.bar_margin
        self.setFixedHeight(self.bar_height)

        self.update()

    def paintEvent(self, event):
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

            bar_color = pytest_run_state.get_qt_bar_color()

            if pytest_run_state.get_state() != PytestRunnerState.QUEUED:
                seconds_from_start = start_running_time - self.min_time_stamp
                x1 = (seconds_from_start * horizontal_pixels_per_second) + self.bar_margin
                y1 = outer_rect.y() + self.bar_margin
                w = ((end_time - start_running_time) * horizontal_pixels_per_second) - (2 * self.bar_margin)
                h = self.one_character_dimensions.height()
                painter.setPen(QPen(bar_color, 1))
                bar_rect = QRectF(x1, y1, w, h)
                painter.fillRect(bar_rect, QBrush(bar_color))

                # save rect and text for tooltip hit-testing
                self._last_bar_rect = bar_rect
                self._last_bar_text = self.status_list[-1].output
            else:
                # nothing drawn
                self._last_bar_rect = None
                self._last_bar_text = ""

            text_left_margin = self.one_character_dimensions.width()
            text_y_margin = int(round((0.5 * self.one_character_dimensions.height() + self.bar_margin + 1)))

            palette = self.palette()
            text_color = palette.color(QPalette.WindowText)
            painter.setPen(QPen(text_color, 1))
            painter.drawText(outer_rect.x() + text_left_margin, outer_rect.y() + text_y_margin, bar_text)

            painter.end()
        else:
            self._last_bar_rect = None
            self._last_bar_text = ""
            super().paintEvent(event)

    def mouseMoveEvent(self, event):
        # get mouse position as QPointF for QRectF.contains
        if hasattr(event, "position"):
            pos = QPointF(event.position())
        else:
            pos = QPointF(event.pos())

        if self._last_bar_rect is not None and self._last_bar_rect.contains(pos):
            # global position may be provided as globalPosition() in Qt6 or globalPos()
            if hasattr(event, "globalPosition"):
                global_pos = event.globalPosition().toPoint()
            else:
                global_pos = event.globalPos()
            QToolTip.showText(global_pos, self._last_bar_text, self)
        else:
            QToolTip.hideText()

        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)
