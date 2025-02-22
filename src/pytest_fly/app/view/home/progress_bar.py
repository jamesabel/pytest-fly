from typing import List, Optional
from datetime import datetime, timedelta

from PySide6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QSizePolicy, QStatusBar, QLabel
from PySide6.QtCore import Qt, QRectF, QPointF, QRect
from PySide6.QtGui import QPainter, QColor, QPen, QPaintEvent


class PytestProgressBar(QWidget):
    def __init__(self, start_time: float, end_time: float, max_time: float, title: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.start_time = start_time
        self.end_time = end_time
        self.max_time = max_time
        self.title = title
        layout = QVBoxLayout()
        self.setLayout(layout)

        # set height of the progress bar
        self.setFixedHeight(50)

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

        # Coordinates for the horizontal bar
        bar_margin_left = 20
        bar_margin_right = 20
        bar_margin_top = 30
        bar_y = outer_rect.y() + bar_margin_top
        bar_left = outer_rect.x() + bar_margin_left
        bar_right = outer_rect.right() - bar_margin_right
        bar_width = bar_right - bar_left
        bar_height = 5  # thickness of the main bar line

        # Clamp start and end times
        clamped_start = max(0, min(self.start_time, self.max_time))
        clamped_end = max(0, min(self.end_time, self.max_time))

        start_x = bar_left + (clamped_start / self.max_time) * bar_width
        end_x = bar_left + (clamped_end / self.max_time) * bar_width

        x1 = bar_left
        y1 = bar_y
        w = bar_width
        h = bar_height
        # Draw the main horizontal bar
        painter.drawRect(x1, y1, w, h)

        # Draw tick marks
        tick_interval = 10  # seconds between ticks (adjust as desired)
        tick_count = int(self.max_time // tick_interval) + 1

        for i in range(tick_count + 1):
            t = i * tick_interval
            if t > self.max_time:
                break

            tick_x = bar_left + (t / self.max_time) * bar_width
            tick_height = 6
            painter.drawLine(tick_x, bar_y - tick_height, tick_x, bar_y + tick_height)

            # Numeric label under the bar
            label_offset = 20
            painter.drawText(tick_x - 5, bar_y + label_offset, f"{t}")

        painter.end()
