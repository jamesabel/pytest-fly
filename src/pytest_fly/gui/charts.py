"""
Shared custom-painted chart widgets and scaffolding.

Two chart families previously lived apart with duplicated painting code: the Run tab's
system-metrics charts (:class:`MetricChart`, extracted from ``system_metrics_window``)
and the Coverage tab's step chart.  Both now share this module: :class:`MetricChart` and
:class:`Series` live here, and :func:`paint_chart_frame` paints the common scaffolding —
geometry with a too-small bail-out, horizontal grid lines with y-axis labels, and
vertical time grid lines — for any custom-painted time chart.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..colors import COMMIT_WARN_COLOR, GRID_LINE_COLOR
from .graph_tab.time_axis import Y_GRID_PCTS, TimeAxisMapping, compute_grid_ticks, format_elapsed_label
from .gui_util import get_text_dimensions, window_text_color

MIN_CHART_HEIGHT = 70  # pixels — each sub-chart minimum


@dataclass(frozen=True)
class ChartFrame:
    """Geometry computed (and scaffolding painted) by :func:`paint_chart_frame`."""

    margin_left: int
    margin_top: int
    margin_bottom: int
    chart_w: int  # plot-area width in pixels
    chart_h: int  # plot-area height in pixels
    grid_ticks: list[tuple[float, str]]  # (x_pixel, elapsed_label) vertical grid ticks, for caller-drawn x labels


def paint_chart_frame(
    painter: QPainter,
    widget: QWidget,
    *,
    y_ticks: list[tuple[float, str]],
    min_ts: float | None,
    max_ts: float | None,
    margin_left: int,
    margin_top: int,
    margin_bottom: int,
    right_inset: int = 0,
) -> ChartFrame | None:
    """Paint the shared chart scaffolding and return the plot geometry.

    Draws the horizontal grid lines with their y-axis labels and the vertical time grid
    lines.  X-axis labels are left to the caller (the two chart families label them
    differently), using the returned :attr:`ChartFrame.grid_ticks`.

    :param painter: Active painter for *widget*.
    :param widget: The chart widget (used for size and palette-aware text color).
    :param y_ticks: ``(fraction, label)`` pairs — *fraction* is the tick's height as a
        fraction of the plot area measured from the bottom (0.0-1.0).
    :param min_ts: Left edge of the time window, or ``None`` when empty.
    :param max_ts: Right edge of the time window, or ``None`` when empty.
    :param margin_left: Pixels reserved for y-axis labels.
    :param margin_top: Pixels reserved above the plot (titles/legends).
    :param margin_bottom: Pixels reserved below the plot (x-axis labels).
    :param right_inset: Pixels of padding on the right edge.
    :return: The painted frame's geometry, or ``None`` when the widget is too small
        (callers must end their painter and return).
    """
    w = widget.width()
    h = widget.height()
    chart_w = w - margin_left - right_inset
    chart_h = h - margin_top - margin_bottom
    if chart_w <= 0 or chart_h <= 0:
        return None

    text_color = window_text_color(widget)

    # Horizontal grid lines, then their y labels.
    painter.setPen(QPen(GRID_LINE_COLOR, 1))
    for fraction, _unused_label in y_ticks:
        y = margin_top + int(chart_h * (1.0 - fraction))
        painter.drawLine(margin_left, y, w - right_inset, y)
    painter.setPen(QPen(text_color, 1))
    for fraction, label in y_ticks:
        y = margin_top + int(chart_h * (1.0 - fraction))
        label_w = get_text_dimensions(label).width()
        painter.drawText(margin_left - label_w - 4, y + 4, label)

    # Vertical time grid lines (labels are caller-drawn from grid_ticks).
    grid_ticks = compute_grid_ticks(min_ts, max_ts, chart_w)
    painter.setPen(QPen(GRID_LINE_COLOR, 1))
    for x, _unused_label in grid_ticks:
        painter.drawLine(int(margin_left + x), margin_top, int(margin_left + x), margin_top + chart_h)

    return ChartFrame(margin_left=margin_left, margin_top=margin_top, margin_bottom=margin_bottom, chart_w=chart_w, chart_h=chart_h, grid_ticks=grid_ticks)


@dataclass(frozen=True)
class Series:
    """One line series on a :class:`MetricChart`."""

    label: str
    color: QColor
    # The getter/formatter read attributes off a duck-typed sample (anything exposing the
    # per-series attributes), so the parameter is typed Any rather than a concrete class.
    getter: Callable[[Any], float]
    legend_formatter: Callable[[Any], str] | None = None


class MetricChart(QWidget):
    """Single time-series chart for one metric family (e.g. CPU or Network).

    Samples are duck-typed: anything with a ``time_stamp`` attribute plus whatever
    attributes the configured :class:`Series` getters read.
    """

    def __init__(self, title: str, series: list[Series], unit: str, y_max_fixed: float | None, integer_y: bool = False):
        """
        :param title: Panel title shown in the top-left of the chart.
        :param series: Line series painted over the same axes.
        :param unit: Unit suffix for y-axis tick labels (``"%"`` or ``"MB/s"``).
        :param y_max_fixed: Fixed y-axis maximum (e.g. ``100.0`` for percent).  ``None`` → auto-scale
            to the largest sample in the current window, with a small minimum so the axis never flattens.
        :param integer_y: When ``True`` the y-axis is treated as whole-number counts (e.g. number of
            tests) — labels are rendered as integers and the auto-scaled maximum is rounded up.
        """
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(MIN_CHART_HEIGHT)

        self._title = title
        self._series = series
        self._unit = unit
        self._y_max_fixed = y_max_fixed
        self._integer_y = integer_y

        self._samples: Sequence[Any] = []
        self._min_ts: float | None = None
        self._max_ts: float | None = None
        # When True, series are painted in the warning color (used by the Commit chart
        # when commit charge crosses the configured threshold).
        self._warn = False

    def update_data(self, samples: Sequence[Any], min_ts: float | None, max_ts: float | None, warn: bool = False):
        """Replace the sample window and repaint."""
        self._samples = samples
        self._min_ts = min_ts
        self._max_ts = max_ts
        self._warn = warn
        self.update()

    def clear_warn(self) -> None:
        """Drop the warning color and repaint immediately (used when a latched warning is cleared)."""
        self._warn = False
        self.update()

    def _current_y_max(self) -> float:
        """Return the y-axis maximum: the fixed value, or an auto-scaled peak with headroom."""
        if self._y_max_fixed is not None:
            return self._y_max_fixed
        peak = 0.0
        for sample in self._samples:
            for series in self._series:
                value = series.getter(sample)
                if value > peak:
                    peak = value
        if self._integer_y:
            return float(max(math.ceil(peak * 1.15), 1))  # whole-number axis, never collapse to zero
        return max(peak * 1.15, 1.0)  # 15% headroom, but never collapse to zero

    def _y_grid_ticks(self, y_max: float) -> list[float]:
        """Y-axis tick values (in data units) for horizontal gridlines and labels.

        Continuous charts (CPU, Memory, MB/s) use evenly spaced fractions of ``y_max``.
        Integer-count charts (e.g. Activity) instead use a whole-number step so the labels
        are always distinct and the top tick lands exactly on ``y_max`` — fixed fractions of
        a small max otherwise round to duplicates (e.g. ``y_max == 1`` → 0, 0, 1, 1).
        """
        if not self._integer_y:
            return [y_max * pct for pct in Y_GRID_PCTS]
        top = max(int(round(y_max)), 1)
        step = max(1, math.ceil(top / len(Y_GRID_PCTS)))
        # Build from the top down so the highest tick is always y_max, then present ascending.
        return [float(value) for value in range(top, 0, -step)][::-1]

    def _format_y_label(self, value: float) -> str:
        """Format a y-axis tick value with the chart's unit and a value-appropriate precision."""
        if self._integer_y:
            return str(int(round(value)))
        if self._unit == "%":
            return f"{int(round(value))}%"
        if value >= 100:
            return f"{value:.0f}{self._unit}"
        if value >= 10:
            return f"{value:.1f}{self._unit}"
        return f"{value:.2f}{self._unit}"

    def paintEvent(self, event):
        """Paint the shared frame, the negative-offset x labels, the title/legend, and the series lines."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        char_h = get_text_dimensions("X").height()

        y_max = self._current_y_max()
        max_label = self._format_y_label(y_max)
        margin_left = get_text_dimensions(max_label + " ").width()
        frac_ticks = [((value / y_max if y_max > 0 else 0.0), self._format_y_label(value)) for value in self._y_grid_ticks(y_max)]

        frame = paint_chart_frame(
            painter,
            self,
            y_ticks=frac_ticks,
            min_ts=self._min_ts,
            max_ts=self._max_ts,
            margin_left=margin_left,
            margin_top=char_h + 4,  # room for title + legend
            margin_bottom=char_h + 4,  # room for x-axis tick labels
            right_inset=4,
        )
        if frame is None:
            painter.end()
            return
        chart_w = frame.chart_w
        chart_h = frame.chart_h
        margin_top = frame.margin_top

        text_color = window_text_color(self)

        # Time-offset tick labels along the bottom — right edge is 0, earlier ticks read as negative
        # (e.g. ``-30s``, ``-2m``).  Skip the first and last ticks to avoid edge overlap.
        if self._min_ts is not None and self._max_ts is not None and len(frame.grid_ticks) > 2:
            time_span = max(self._max_ts - self._min_ts, 1.0)
            painter.setPen(QPen(text_color, 1))
            label_y = margin_top + chart_h + char_h
            for x, _elapsed_label in frame.grid_ticks[1:-1]:
                offset_seconds = time_span - (x / chart_w) * time_span
                label = "0" if offset_seconds <= 0 else f"-{format_elapsed_label(offset_seconds)}"
                label_w = get_text_dimensions(label).width()
                label_x = int(margin_left + x) - label_w // 2
                painter.drawText(label_x, label_y, label)

        # Title and legend (with current values) across the top
        painter.setPen(QPen(text_color, 1))
        painter.drawText(margin_left, char_h, self._title)

        legend_parts: list[tuple[str, QColor]] = []
        latest = self._samples[-1] if self._samples else None
        for series in self._series:
            if latest is None:
                value_text = "--"
            elif series.legend_formatter is not None:
                value_text = series.legend_formatter(latest)
            else:
                value_text = self._format_y_label(series.getter(latest))
            legend_parts.append((f"{series.label}: {value_text}", series.color))

        legend_x = margin_left + get_text_dimensions(self._title + "    ").width()
        for text, color in legend_parts:
            painter.setPen(QPen(COMMIT_WARN_COLOR if self._warn else color, 1))
            painter.drawText(legend_x, char_h, text)
            legend_x += get_text_dimensions(text + "   ").width()

        # Data lines
        if self._samples and self._min_ts is not None and self._max_ts is not None and self._max_ts > self._min_ts:
            mapping = TimeAxisMapping(min_ts=self._min_ts, max_ts=self._max_ts, width_pixels=chart_w)
            for series in self._series:
                painter.setPen(QPen(COMMIT_WARN_COLOR if self._warn else series.color, 2))
                prev_x: int | None = None
                prev_y: int | None = None
                for sample in self._samples:
                    x = margin_left + int(mapping.ts_to_x(sample.time_stamp))
                    value = series.getter(sample)
                    clamped = max(0.0, min(value, y_max))
                    y = margin_top + int(chart_h * (1.0 - (clamped / y_max if y_max > 0 else 0.0)))
                    if prev_x is not None and prev_y is not None:
                        painter.drawLine(prev_x, prev_y, x, y)
                    prev_x = x
                    prev_y = y

        painter.end()
