"""
Progress bar widget — custom-painted horizontal bar showing a single test's
execution timeline with change-detection optimization to skip unnecessary repaints.
"""

import time

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QBrush, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QMenu, QToolTip, QVBoxLayout, QWidget
from typeguard import typechecked

from ...colors import GRID_LINE_COLOR
from ...interfaces import PytestProcessInfo, PytestRunnerState
from ...logger import get_logger
from ...pytest_runner.pytest_runner import PytestRunState
from ..gui_util import get_text_dimensions, tool_tip_limiter, window_text_color
from .time_axis import TimeAxisMapping, compute_grid_ticks

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
        run_state: PytestRunState,
        is_singleton: bool = False,
    ) -> None:

        super().__init__()
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.one_character_dimensions = get_text_dimensions("X")

        self.status_list = status_list
        self.min_time_stamp = min_time_stamp
        self.max_time_stamp = max_time_stamp
        self._run_state = run_state
        self._is_singleton = is_singleton

        if len(status_list) > 0:
            name = status_list[0].name
            name_text_dimensions = get_text_dimensions(name)
        else:
            name_text_dimensions = self.one_character_dimensions
        self.bar_margin = 1
        self.bar_height = name_text_dimensions.height() + 2 * self.bar_margin
        self.setFixedHeight(self.bar_height)
        log.debug(f"{self.bar_height=},{name_text_dimensions=}")

        # --- Tooltip-related state ---
        self.setMouseTracking(True)  # receive mouseMoveEvent even with no button pressed
        self._last_bar_rect: QRectF | None = None
        self._last_bar_text: str = ""

        # --- Change-detection state (must be initialized before first update call) ---
        self._prev_count: int = 0
        self._prev_last_ts: float | None = None
        self._prev_min_ts: float | None = None
        self._prev_max_ts: float | None = None

        self.update_pytest_process_info(status_list, min_time_stamp, max_time_stamp, run_state, is_singleton)

    def update_pytest_process_info(self, status_list: list[PytestProcessInfo], min_time_stamp: float, max_time_stamp: float, run_state: PytestRunState, is_singleton: bool = False):
        """
        Update the bar's data and schedule a repaint — but only if the data
        actually changed or the test is still running (its bar grows over time).
        """
        # O(1) change detection: skip repaint if nothing changed
        new_count = len(status_list)
        new_last_ts = status_list[-1].time_stamp if status_list else None
        is_running = len(status_list) > 0 and status_list[-1].pid is not None and run_state.get_state() == PytestRunnerState.RUNNING
        singleton_changed = is_singleton != self._is_singleton
        unchanged = (
            not is_running
            and not singleton_changed
            and new_count == self._prev_count
            and new_last_ts == self._prev_last_ts
            and min_time_stamp == self._prev_min_ts
            and max_time_stamp == self._prev_max_ts
        )
        if unchanged:
            return  # no change — skip repaint
        self._prev_count = new_count
        self._prev_last_ts = new_last_ts
        self._prev_min_ts = min_time_stamp
        self._prev_max_ts = max_time_stamp

        self.status_list = status_list
        self.min_time_stamp = min_time_stamp
        self.max_time_stamp = max_time_stamp
        self._run_state = run_state
        self._is_singleton = is_singleton

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
            pytest_run_state = self._run_state

            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)

            # Draw vertical grid lines (behind the bar)
            grid_ticks = compute_grid_ticks(self.min_time_stamp, self.max_time_stamp, self.width())
            painter.setPen(QPen(GRID_LINE_COLOR, 1))
            for x, _label in grid_ticks:
                painter.drawLine(int(x), 0, int(x), self.height())

            if pytest_run_state.get_state() in (PytestRunnerState.QUEUED, PytestRunnerState.STOPPED) or len(self.status_list) < 2:
                start_running_time = None
            else:
                start_running_time = self.status_list[1].time_stamp

            if pytest_run_state.get_state() == PytestRunnerState.RUNNING:
                end_time = time.time()
            else:
                end_time = self.status_list[-1].time_stamp

            name_label = pytest_run_state.get_name()
            if self._is_singleton:
                name_label = f"{name_label} (singleton)"
            bar_text = f"{name_label} - {pytest_run_state.get_string()}"

            outer_rect = self.rect()
            mapping = TimeAxisMapping(min_ts=self.min_time_stamp, max_ts=self.max_time_stamp, width_pixels=outer_rect.width())

            bar_color = pytest_run_state.get_qt_bar_color()

            if pytest_run_state.get_state() not in (PytestRunnerState.QUEUED, PytestRunnerState.STOPPED) and start_running_time is not None and end_time >= self.min_time_stamp:
                x1 = mapping.ts_to_x(start_running_time) + self.bar_margin
                y1 = outer_rect.y() + self.bar_margin
                w = mapping.elapsed_to_x(end_time - start_running_time) - (2 * self.bar_margin)
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

            painter.setPen(QPen(window_text_color(self), 1))
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
            QToolTip.showText(global_pos, tool_tip_limiter(self._last_bar_text), self)
        else:
            QToolTip.hideText()

        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)

    def contextMenuEvent(self, event):
        """Right-click menu: Copy the current tooltip text to the clipboard."""
        menu = QMenu(self)
        copy_action = menu.addAction("Copy Pytest Output")
        selected = menu.exec(event.globalPos())

        if selected == copy_action:
            tooltip = self._last_bar_text or ""
            if tooltip:
                QGuiApplication.clipboard().setText(str(tooltip))
