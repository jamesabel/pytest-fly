from typing import List
from datetime import datetime, timedelta

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QPaintEvent


class Process:
    def __init__(self, name: str, start: datetime, stop: datetime) -> None:
        self.name = name
        self.start = start
        self.stop = stop


class ProgressBars(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.processes = []
        # Use a fixed timeline start for reference.
        self.timeline_start = datetime.now()
        self.timeline_duration = timedelta(minutes=6)  # 60 minutes timeline
        self.setMinimumSize(800, 300)
        self.setWindowTitle("Process Timeline Monitor")

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        rect = self.rect()
        canvas_width = rect.width()

        # Define timeline parameters
        total_seconds = self.timeline_duration.total_seconds()

        # Draw time axis
        axis_y = 50
        painter.drawLine(0, axis_y, canvas_width, axis_y)

        tick_interval = 1  # minutes
        num_ticks = int(self.timeline_duration.total_seconds() // (tick_interval * 60)) + 1
        for i in range(num_ticks):
            minute = i * tick_interval
            x = (minute / 60) * canvas_width  # since timeline_duration=60min
            painter.drawLine(QPointF(x, axis_y - 5), QPointF(x, axis_y + 5))
            painter.drawText(int(x) - 10, axis_y - 10, f"{minute}m")

        # Draw process bars
        bar_height = 20
        vertical_padding = 10
        for idx, process in enumerate(self.processes):
            # Calculate vertical position for this process's bar
            y = axis_y + vertical_padding + idx * (bar_height + vertical_padding)
            # Calculate start and stop offsets in seconds (relative to the timeline start)
            start_offset = (process.start - self.timeline_start).total_seconds()
            stop_offset = (process.stop - self.timeline_start).total_seconds()
            # Map time to x-coordinates on the canvas
            x_start = (start_offset / total_seconds) * canvas_width
            x_stop = (stop_offset / total_seconds) * canvas_width

            # Draw the rectangle for the process bar
            rect_bar = QRectF(x_start, y, x_stop - x_start, bar_height)
            painter.setBrush(QColor("skyblue"))
            painter.drawRect(rect_bar)

            # Draw process name (to the left of the bar)
            painter.setPen(QPen(Qt.black))
            painter.drawText(int(x_start) - 5, int(y + bar_height / 2 + 5), process.name)

    def update_processes(self, new_processes: List[Process]) -> None:
        """
        Update the list of processes and refresh the timeline.
        """
        self.processes = new_processes
        self.update()
