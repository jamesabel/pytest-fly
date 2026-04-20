"""
Run-tab system-performance widget — stacked charts of system-wide CPU, memory,
disk I/O, and network I/O sampled by :class:`SystemMonitor` in a separate process.

The widget keeps a time-pruned ring buffer of :class:`SystemMonitorSample` records
and repaints from that buffer.  Sampling runs in a subprocess (owned by the main
window), so the GUI thread only does a non-blocking queue drain + a `QPainter`
repaint per tick.

Chart style follows ``coverage_tab._CoverageChart`` — custom ``QPainter`` with
``TimeAxisMapping`` + ``compute_grid_ticks`` from the graph-tab time-axis module.
"""

import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QGroupBox, QSizePolicy, QWidget

from ...colors import CPU_LINE_COLOR, DISK_READ_COLOR, DISK_WRITE_COLOR, GRID_LINE_COLOR, MEMORY_LINE_COLOR, NET_RECV_COLOR, NET_SENT_COLOR
from ...preferences import get_pref
from ...pytest_runner.system_monitor import SystemMonitorSample
from ..graph_tab.time_axis import TimeAxisMapping, compute_grid_ticks, format_elapsed_label
from ..gui_util import get_text_dimensions, window_text_color

_Y_GRID_PCTS = [0.25, 0.50, 0.75, 1.00]
_MIN_CHART_HEIGHT = 70  # pixels — each sub-chart minimum


@dataclass(frozen=True)
class _Series:
    """One line series on a :class:`_MetricChart`."""

    label: str
    color: QColor
    getter: Callable[[SystemMonitorSample], float]


class _MetricChart(QWidget):
    """Single time-series chart for one metric family (e.g. CPU or Network)."""

    def __init__(self, title: str, series: list[_Series], unit: str, y_max_fixed: float | None):
        """
        :param title: Panel title shown in the top-left of the chart.
        :param series: Line series painted over the same axes.
        :param unit: Unit suffix for y-axis tick labels (``"%"`` or ``"MB/s"``).
        :param y_max_fixed: Fixed y-axis maximum (e.g. ``100.0`` for percent).  ``None`` → auto-scale
            to the largest sample in the current window, with a small minimum so the axis never flattens.
        """
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(_MIN_CHART_HEIGHT)

        self._title = title
        self._series = series
        self._unit = unit
        self._y_max_fixed = y_max_fixed

        self._samples: list[SystemMonitorSample] = []
        self._min_ts: float | None = None
        self._max_ts: float | None = None

    def update_data(self, samples: list[SystemMonitorSample], min_ts: float | None, max_ts: float | None):
        self._samples = samples
        self._min_ts = min_ts
        self._max_ts = max_ts
        self.update()

    def _current_y_max(self) -> float:
        if self._y_max_fixed is not None:
            return self._y_max_fixed
        peak = 0.0
        for sample in self._samples:
            for series in self._series:
                value = series.getter(sample)
                if value > peak:
                    peak = value
        return max(peak * 1.15, 1.0)  # 15% headroom, but never collapse to zero

    def _format_y_label(self, value: float) -> str:
        if self._unit == "%":
            return f"{int(round(value))}%"
        if value >= 100:
            return f"{value:.0f}{self._unit}"
        if value >= 10:
            return f"{value:.1f}{self._unit}"
        return f"{value:.2f}{self._unit}"

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        char_h = get_text_dimensions("X").height()

        y_max = self._current_y_max()
        max_label = self._format_y_label(y_max)
        margin_left = get_text_dimensions(max_label + " ").width()
        margin_top = char_h + 4  # room for title + legend
        margin_bottom = char_h + 4  # room for x-axis tick labels
        chart_w = w - margin_left - 4
        chart_h = h - margin_top - margin_bottom

        if chart_w <= 0 or chart_h <= 0:
            painter.end()
            return

        text_color = window_text_color(self)

        # Horizontal grid lines + y labels
        painter.setPen(QPen(GRID_LINE_COLOR, 1))
        for pct in _Y_GRID_PCTS:
            y = margin_top + int(chart_h * (1.0 - pct))
            painter.drawLine(margin_left, y, w - 4, y)

        painter.setPen(QPen(text_color, 1))
        for pct in _Y_GRID_PCTS:
            y = margin_top + int(chart_h * (1.0 - pct))
            label = self._format_y_label(y_max * pct)
            label_w = get_text_dimensions(label).width()
            painter.drawText(margin_left - label_w - 4, y + 4, label)

        # Vertical grid lines + x tick labels (bottom chart only would be ideal, but painting
        # on every sub-chart keeps each chart standalone and is cheap).
        grid_ticks = compute_grid_ticks(self._min_ts, self._max_ts, chart_w)
        painter.setPen(QPen(GRID_LINE_COLOR, 1))
        for x, _label in grid_ticks:
            painter.drawLine(int(margin_left + x), margin_top, int(margin_left + x), margin_top + chart_h)

        # Time-offset tick labels along the bottom — right edge is 0, earlier ticks read as negative
        # (e.g. ``-30s``, ``-2m``).  Skip the first and last ticks to avoid edge overlap.
        if self._min_ts is not None and self._max_ts is not None and len(grid_ticks) > 2:
            time_span = max(self._max_ts - self._min_ts, 1.0)
            painter.setPen(QPen(text_color, 1))
            label_y = margin_top + chart_h + char_h
            for x, _elapsed_label in grid_ticks[1:-1]:
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
            value_text = self._format_y_label(series.getter(latest)) if latest is not None else "--"
            legend_parts.append((f"{series.label}: {value_text}", series.color))

        legend_x = margin_left + get_text_dimensions(self._title + "    ").width()
        for text, color in legend_parts:
            painter.setPen(QPen(color, 1))
            painter.drawText(legend_x, char_h, text)
            legend_x += get_text_dimensions(text + "   ").width()

        # Data lines
        if self._samples and self._min_ts is not None and self._max_ts is not None and self._max_ts > self._min_ts:
            mapping = TimeAxisMapping(min_ts=self._min_ts, max_ts=self._max_ts, width_pixels=chart_w)
            for series in self._series:
                painter.setPen(QPen(series.color, 2))
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


class SystemMetricsWindow(QGroupBox):
    """Container panel with four stacked sub-charts (CPU, Memory, Disk, Network)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("System Performance")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QGridLayout()
        self.setLayout(layout)

        self._cpu_chart = _MetricChart(
            title="CPU",
            series=[_Series(label="usage", color=CPU_LINE_COLOR, getter=lambda s: s.cpu_percent)],
            unit="%",
            y_max_fixed=100.0,
        )
        self._memory_chart = _MetricChart(
            title="Memory",
            series=[_Series(label="usage", color=MEMORY_LINE_COLOR, getter=lambda s: s.memory_percent)],
            unit="%",
            y_max_fixed=100.0,
        )
        self._disk_chart = _MetricChart(
            title="Disk",
            series=[
                _Series(label="read", color=DISK_READ_COLOR, getter=lambda s: s.disk_read_mbps),
                _Series(label="write", color=DISK_WRITE_COLOR, getter=lambda s: s.disk_write_mbps),
            ],
            unit="MB/s",
            y_max_fixed=None,
        )
        self._network_chart = _MetricChart(
            title="Network",
            series=[
                _Series(label="sent", color=NET_SENT_COLOR, getter=lambda s: s.net_sent_mbps),
                _Series(label="recv", color=NET_RECV_COLOR, getter=lambda s: s.net_recv_mbps),
            ],
            unit="MB/s",
            y_max_fixed=None,
        )

        # 2x2 grid: CPU + Memory stacked in the left column, Disk + Network stacked in the right column.
        layout.addWidget(self._cpu_chart, 0, 0)
        layout.addWidget(self._memory_chart, 1, 0)
        layout.addWidget(self._disk_chart, 0, 1)
        layout.addWidget(self._network_chart, 1, 1)
        layout.setRowStretch(0, 1)
        layout.setRowStretch(1, 1)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)

        self._samples: deque[SystemMonitorSample] = deque()

    def ingest_samples(self, samples: Iterable[SystemMonitorSample]) -> None:
        """Append new samples to the ring buffer (called once per GUI tick)."""
        for sample in samples:
            self._samples.append(sample)

    def update_tick(self) -> None:
        """Prune stale samples and repaint all four sub-charts."""
        window_seconds = max(get_pref().chart_window_minutes, 0.5) * 60.0
        now = time.time()
        cutoff = now - window_seconds
        while self._samples and self._samples[0].time_stamp < cutoff:
            self._samples.popleft()

        # Time axis always spans the full configured window ending at "now" so the charts
        # animate smoothly (the right edge is always the current moment).
        min_ts = now - window_seconds
        max_ts = now
        samples_list = list(self._samples)

        self._cpu_chart.update_data(samples_list, min_ts, max_ts)
        self._memory_chart.update_data(samples_list, min_ts, max_ts)
        self._disk_chart.update_data(samples_list, min_ts, max_ts)
        self._network_chart.update_data(samples_list, min_ts, max_ts)
