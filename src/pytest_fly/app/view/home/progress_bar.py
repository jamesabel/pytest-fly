from typing import List, Optional
from datetime import datetime, timedelta

from PySide6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QSizePolicy, QStatusBar, QLabel
from PySide6.QtCore import Qt, QRectF, QPointF, QRect
from PySide6.QtGui import QPainter, QColor, QPen, QPaintEvent


class PytestProgressBar(QWidget):
    def __init__(self, start_time: float, end_time: float, min_time_stamp: float, max_time_stamp: float, title: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.start_time = start_time
        self.end_time = end_time
        self.min_time_stamp = min_time_stamp
        self.max_time_stamp = max_time_stamp
        self.title = title
        layout = QVBoxLayout()
        self.setLayout(layout)

        # set height of the progress bar
        self.setFixedHeight(50)

    def update_status(self, start_time: float, end_time: float, min_time_stamp: float, max_time_stamp: float) -> None:
        self.start_time = start_time
        self.end_time = end_time
        self.min_time_stamp = min_time_stamp
        self.max_time_stamp = max_time_stamp
        self.update()

    def update_time_window(self, min_time_stamp: float, max_time_stamp: float) -> None:
        self.min_time_stamp = min_time_stamp
        self.max_time_stamp = max_time_stamp
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        outer_rect = self.rect()
        pen = QPen(Qt.black, 1)
        painter.setPen(pen)
        # painter.drawRect(outer_rect)

        # Title near the top
        title_margin = 20
        painter.drawText(outer_rect.x() + 10, outer_rect.y() + title_margin, self.title)

        overall_time_window = max(self.max_time_stamp - self.min_time_stamp, 1)  # a least 1 second
        horizontal_pixels_per_second = outer_rect.width() / overall_time_window

        # Coordinates for the horizontal bar
        x1 = int(round((self.start_time - self.min_time_stamp) * horizontal_pixels_per_second))
        y1 = outer_rect.y() + 10
        w = int(round((self.end_time - self.start_time) * horizontal_pixels_per_second))
        h = 10
        # Draw the main horizontal bar
        painter.drawRect(x1, y1, w, h)

        # # Draw tick marks
        # tick_interval = 10  # seconds between ticks (adjust as desired)
        # tick_count = int(self.end_time // tick_interval) + 1
        #
        # for i in range(tick_count + 1):
        #     t = i * tick_interval
        #     if t > self.end_time:
        #         break
        #
        #     tick_x = bar_left + (t / self.end_time) * bar_width
        #     tick_height = 6
        #     painter.drawLine(tick_x, bar_y - tick_height, tick_x, bar_y + tick_height)
        #
        #     # Numeric label under the bar
        #     label_offset = 20
        #     painter.drawText(tick_x - 5, bar_y + label_offset, f"{t}")

        painter.end()
