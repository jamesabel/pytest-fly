"""
Time-axis header and grid-line utilities for the Graph tab.

Provides:
- :class:`TimeAxisMapping`: encapsulates the timestamp → pixel-x conversion
  used by the progress bars, the axis header, and the coverage chart.
- :func:`compute_grid_ticks`: grid tick positions/labels derived from a
  :class:`TimeAxisMapping`.
- :class:`TimeAxisWidget`: the header painted at the top of the progress-bar list.
"""

from dataclasses import dataclass

from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QWidget

from ...colors import GRID_LINE_COLOR
from ..gui_util import get_text_dimensions, window_text_color

# Candidate intervals in seconds — chosen so labels stay readable.
# Extends up to 24h so multi-hour runs don't collapse to minute-granularity grid lines.
_INTERVALS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400]


@dataclass(frozen=True)
class TimeAxisMapping:
    """
    Maps wall-clock timestamps to pixel x-coordinates along a time axis.

    Shared by :class:`PytestProgressBar`, :class:`TimeAxisWidget`, and the
    coverage chart so every site agrees on the same math (time-window clamp,
    pixels-per-second, and ts → x conversion).
    """

    min_ts: float
    max_ts: float
    width_pixels: float

    @property
    def time_window(self) -> float:
        """Seconds spanned by the axis, clamped to at least 1.0 so divisions never explode."""
        return max(self.max_ts - self.min_ts, 1.0)

    @property
    def pixels_per_second(self) -> float:
        """Horizontal pixels per elapsed second."""
        return self.width_pixels / self.time_window

    def ts_to_x(self, ts: float) -> float:
        """Convert a wall-clock timestamp to a pixel x-offset (0 at ``min_ts``)."""
        return (ts - self.min_ts) * self.pixels_per_second

    def elapsed_to_x(self, elapsed_seconds: float) -> float:
        """Convert seconds elapsed from ``min_ts`` to a pixel x-offset."""
        return elapsed_seconds * self.pixels_per_second


def _choose_interval(time_window: float) -> float:
    """Pick a tick interval that yields roughly 5-12 grid lines."""
    for interval in _INTERVALS:
        if time_window / interval <= 12:
            return interval
    return _INTERVALS[-1]


def _format_tick_label(elapsed_seconds: float) -> str:
    """Format an elapsed-time value into a compact label (e.g. ``'30s'``, ``'2m'``, ``'3h'``, ``'1h30m'``)."""
    if elapsed_seconds < 60:
        return f"{int(elapsed_seconds)}s"
    if elapsed_seconds < 3600:
        minutes = int(elapsed_seconds // 60)
        seconds = int(elapsed_seconds % 60)
        if seconds == 0:
            return f"{minutes}m"
        return f"{minutes}m{seconds}s"
    hours = int(elapsed_seconds // 3600)
    minutes = int((elapsed_seconds % 3600) // 60)
    if minutes == 0:
        return f"{hours}h"
    return f"{hours}h{minutes}m"


def compute_grid_ticks(min_ts: float | None, max_ts: float | None, width_pixels: int) -> list[tuple[float, str]]:
    """
    Compute X-pixel positions and labels for time-axis grid lines.

    :param min_ts: Earliest timestamp (epoch seconds), or ``None``.
    :param max_ts: Latest timestamp (epoch seconds), or ``None``.
    :param width_pixels: Widget width in pixels.
    :return: List of ``(x_pixel, label_text)`` tuples.
    """
    if min_ts is None or max_ts is None or width_pixels <= 0:
        return []

    mapping = TimeAxisMapping(min_ts=min_ts, max_ts=max_ts, width_pixels=width_pixels)
    interval = _choose_interval(mapping.time_window)

    ticks: list[tuple[float, str]] = []
    elapsed = 0.0
    while elapsed <= mapping.time_window:
        ticks.append((mapping.elapsed_to_x(elapsed), _format_tick_label(elapsed)))
        elapsed += interval

    return ticks


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
        painter.setPen(QPen(window_text_color(self), 1))
        for x, label in ticks:
            label_width = get_text_dimensions(label).width()
            # Center label on tick; clamp so it doesn't overflow the left edge
            label_x = max(int(x) - label_width // 2, 0)
            label_y = h - tick_height - 2  # just above the tick mark
            painter.drawText(label_x, label_y, label)

        painter.end()
