"""
Time-axis header and grid-line utilities for the Graph tab.

Provides :func:`compute_grid_ticks` (shared between the axis header and
individual progress bars) and :class:`TimeAxisWidget` (the header painted
at the top of the progress-bar list).
"""

from PySide6.QtGui import QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import QWidget

from ..gui_util import get_text_dimensions

# Candidate intervals in seconds — chosen so labels stay readable.
_INTERVALS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600]


def _choose_interval(time_window: float) -> float:
    """Pick a tick interval that yields roughly 5-12 grid lines."""
    for interval in _INTERVALS:
        if time_window / interval <= 12:
            return interval
    return _INTERVALS[-1]


def _format_tick_label(elapsed_seconds: float) -> str:
    """Format an elapsed-time value into a compact label (e.g. ``'30s'``, ``'2m'``)."""
    if elapsed_seconds < 60:
        return f"{int(elapsed_seconds)}s"
    minutes = int(elapsed_seconds // 60)
    seconds = int(elapsed_seconds % 60)
    if seconds == 0:
        return f"{minutes}m"
    return f"{minutes}m{seconds}s"


def compute_grid_ticks(min_ts: float | None, max_ts: float | None, width_pixels: int) -> list[tuple[float, str]]:
    """
    Compute X-pixel positions and labels for time-axis grid lines.

    Uses the same time-to-pixel mapping as :class:`PytestProgressBar`:
    ``x = elapsed * (width / time_window)``.

    :param min_ts: Earliest timestamp (epoch seconds), or ``None``.
    :param max_ts: Latest timestamp (epoch seconds), or ``None``.
    :param width_pixels: Widget width in pixels.
    :return: List of ``(x_pixel, label_text)`` tuples.
    """
    if min_ts is None or max_ts is None or width_pixels <= 0:
        return []

    time_window = max(max_ts - min_ts, 1.0)
    pixels_per_second = width_pixels / time_window
    interval = _choose_interval(time_window)

    ticks: list[tuple[float, str]] = []
    elapsed = 0.0
    while elapsed <= time_window:
        x = elapsed * pixels_per_second
        ticks.append((x, _format_tick_label(elapsed)))
        elapsed += interval

    return ticks


# Grid line color — light gray, semi-transparent so bars remain readable.
GRID_LINE_COLOR = QColor(180, 180, 180, 100)


class TimeAxisWidget(QWidget):
    """Compact header widget that draws time-axis labels and short tick marks."""

    def __init__(self):
        super().__init__()
        char_dims = get_text_dimensions("X")
        self._axis_height = char_dims.height() + 8  # text + small padding
        self.setFixedHeight(self._axis_height)

        self._min_ts: float | None = None
        self._max_ts: float | None = None

    def update_time_window(self, min_ts: float | None, max_ts: float | None):
        """Store the current time window and schedule a repaint."""
        if min_ts == self._min_ts and max_ts == self._max_ts:
            return
        self._min_ts = min_ts
        self._max_ts = max_ts
        self.update()

    def paintEvent(self, event):
        ticks = compute_grid_ticks(self._min_ts, self._max_ts, self.width())
        if not ticks:
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        h = self.height()
        tick_height = 5  # short tick mark at the bottom of the axis

        # Draw tick marks
        painter.setPen(QPen(GRID_LINE_COLOR, 1))
        for x, _label in ticks:
            painter.drawLine(int(x), h - tick_height, int(x), h)

        # Draw labels
        palette = self.palette()
        text_color = palette.color(QPalette.WindowText)
        painter.setPen(QPen(text_color, 1))
        for x, label in ticks:
            label_width = get_text_dimensions(label).width()
            # Center label on tick; clamp so it doesn't overflow the left edge
            label_x = max(int(x) - label_width // 2, 0)
            label_y = h - tick_height - 2  # just above the tick mark
            painter.drawText(label_x, label_y, label)

        painter.end()
