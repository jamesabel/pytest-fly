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

import math
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from ...colors import COMMIT_LINE_COLOR, COMMIT_WARN_COLOR, CPU_LINE_COLOR, DISK_READ_COLOR, DISK_WRITE_COLOR, GRID_LINE_COLOR, MEMORY_LINE_COLOR, NET_RECV_COLOR, NET_SENT_COLOR
from ...interfaces import PytestRunnerState
from ...preferences import get_pref
from ...pytest_runner.commit_memory import commit_warning_active
from ...pytest_runner.system_monitor import SystemMonitorSample
from ...tick_data import TickData
from ..graph_tab.time_axis import TimeAxisMapping, compute_grid_ticks, format_elapsed_label
from ..gui_util import get_text_dimensions, window_text_color

# Activity-chart line colors: tests that are running vs. those sampled idle (near-zero CPU).
ACTIVITY_RUNNING_COLOR = QColor("#2e7d32")  # green
ACTIVITY_IDLE_COLOR = QColor("#b25400")  # amber (matches the warning accent)

_Y_GRID_PCTS = [0.25, 0.50, 0.75, 1.00]
_MIN_CHART_HEIGHT = 70  # pixels — each sub-chart minimum


@dataclass(frozen=True)
class _Series:
    """One line series on a :class:`_MetricChart`."""

    label: str
    color: QColor
    getter: Callable[[object], float]
    legend_formatter: Callable[[object], str] | None = None


@dataclass(frozen=True)
class _ActivitySample:
    """One time-stamped snapshot of in-flight test activity for the Activity chart."""

    time_stamp: float
    running: int  # tests in the RUNNING state
    idle: int  # running tests whose subtree CPU is below the idle epsilon
    stalled: bool  # the watchdog has flagged the run as stalled


class _MetricChart(QWidget):
    """Single time-series chart for one metric family (e.g. CPU or Network)."""

    def __init__(self, title: str, series: list[_Series], unit: str, y_max_fixed: float | None, integer_y: bool = False):
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
        self.setMinimumHeight(_MIN_CHART_HEIGHT)

        self._title = title
        self._series = series
        self._unit = unit
        self._y_max_fixed = y_max_fixed
        self._integer_y = integer_y

        self._samples: list[SystemMonitorSample] = []
        self._min_ts: float | None = None
        self._max_ts: float | None = None
        # When True, series are painted in the warning color (used by the Commit chart
        # when commit charge crosses the configured threshold).
        self._warn = False

    def update_data(self, samples: list[SystemMonitorSample], min_ts: float | None, max_ts: float | None, warn: bool = False):
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
            return [y_max * pct for pct in _Y_GRID_PCTS]
        top = max(int(round(y_max)), 1)
        step = max(1, math.ceil(top / len(_Y_GRID_PCTS)))
        # Build from the top down so the highest tick is always y_max, then present ascending.
        return [float(value) for value in range(top, 0, -step)][::-1]

    def _format_y_label(self, value: float) -> str:
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

        # Horizontal grid lines + y labels (tick values are in data units so integer-count
        # charts get distinct whole-number labels rather than rounded fractions).
        y_ticks = self._y_grid_ticks(y_max)
        painter.setPen(QPen(GRID_LINE_COLOR, 1))
        for value in y_ticks:
            pct = value / y_max if y_max > 0 else 0.0
            y = margin_top + int(chart_h * (1.0 - pct))
            painter.drawLine(margin_left, y, w - 4, y)

        painter.setPen(QPen(text_color, 1))
        for value in y_ticks:
            pct = value / y_max if y_max > 0 else 0.0
            y = margin_top + int(chart_h * (1.0 - pct))
            label = self._format_y_label(value)
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
            series=[
                _Series(
                    label="usage",
                    color=MEMORY_LINE_COLOR,
                    getter=lambda s: s.memory_percent,
                    legend_formatter=lambda s: f"{s.memory_used_gb:.1f}/{s.memory_total_gb:.1f} GB ({s.memory_percent:.0f}%)",
                )
            ],
            unit="%",
            y_max_fixed=100.0,
        )
        self._commit_chart = _MetricChart(
            title="Commit",
            series=[
                _Series(
                    label="charge",
                    color=COMMIT_LINE_COLOR,
                    getter=lambda s: s.commit_percent,
                    legend_formatter=lambda s: "N/A" if s.commit_total_gb <= 0 else f"{s.commit_used_gb:.1f}/{s.commit_total_gb:.1f} GB ({s.commit_percent:.0f}%)",
                )
            ],
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

        # Test-activity chart — running vs. idle in-flight test counts over time. Plotted like the
        # other charts so a wedge is visible at a glance (idle climbs to meet running). Lines turn
        # warning-colored while the stall watchdog has the run flagged as stalled.
        self._activity_chart = _MetricChart(
            title="Activity",
            series=[
                _Series(label="running", color=ACTIVITY_RUNNING_COLOR, getter=lambda s: float(s.running), legend_formatter=lambda s: str(s.running)),
                _Series(label="idle", color=ACTIVITY_IDLE_COLOR, getter=lambda s: float(s.idle), legend_formatter=lambda s: str(s.idle)),
            ],
            unit="",
            y_max_fixed=None,
            integer_y=True,
        )
        self._activity_chart.setToolTip(
            "In-flight test activity over time.\n\n"
            "'running' = tests currently executing; 'idle' = running tests whose subtree CPU is below\n"
            "the configured CPU Idle Epsilon (a deadlocked process tree sits near 0% CPU). When idle\n"
            "rises to meet running and stays there with no progress for the Stall Warn Window, the run\n"
            "is flagged stalled and these lines turn orange. Configure thresholds in the Configuration tab."
        )

        # 3x2 grid: CPU + Memory + Commit in the left column; Disk + Network + Activity in the right.
        layout.addWidget(self._cpu_chart, 0, 0)
        layout.addWidget(self._memory_chart, 1, 0)
        layout.addWidget(self._commit_chart, 2, 0)
        layout.addWidget(self._disk_chart, 0, 1)
        layout.addWidget(self._network_chart, 1, 1)
        layout.addWidget(self._activity_chart, 2, 1)

        # Warning banner — latched: raised once commit charge crosses the threshold and held (banner +
        # orange Commit chart) until the user clicks "Clear", so a transient spike that has already
        # dropped back below the threshold is not missed. Spans the full width beneath the chart grid so
        # it never steals a chart cell, with the "Clear" button pinned to the right.
        self._commit_warning_latched = False
        self._commit_warning_label = QLabel("")
        self._commit_warning_label.setWordWrap(True)
        self._commit_warning_label.setStyleSheet("color: #b25400;")  # warning orange (matches the Configuration-tab restart notice)

        self._commit_warning_clear_button = QPushButton("Clear")
        self._commit_warning_clear_button.setToolTip("Dismiss the commit-charge warning. It reappears if the commit charge crosses the threshold again.")
        self._commit_warning_clear_button.clicked.connect(self._clear_commit_warning)

        self._commit_warning_widget = QWidget()
        warning_layout = QHBoxLayout(self._commit_warning_widget)
        warning_layout.setContentsMargins(0, 0, 0, 0)
        warning_layout.addWidget(self._commit_warning_label, 1)
        warning_layout.addWidget(self._commit_warning_clear_button, 0)
        self._commit_warning_widget.setVisible(False)
        layout.addWidget(self._commit_warning_widget, 3, 0, 1, 2)

        layout.setRowStretch(0, 1)
        layout.setRowStretch(1, 1)
        layout.setRowStretch(2, 1)
        layout.setRowStretch(3, 0)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)

        self._samples: deque[SystemMonitorSample] = deque()
        self._activity_samples: deque[_ActivitySample] = deque()

    def ingest_samples(self, samples: Iterable[SystemMonitorSample]) -> None:
        """Append new samples to the ring buffer (called once per GUI tick)."""
        for sample in samples:
            self._samples.append(sample)

    def update_tick(self, tick: TickData | None = None) -> None:
        """Prune stale samples, repaint all sub-charts, and append/repaint the activity chart."""
        window_seconds = max(get_pref().chart_window_minutes, 0.5) * 60.0
        now = time.time()
        cutoff = now - window_seconds
        while self._samples and self._samples[0].time_stamp < cutoff:
            self._samples.popleft()

        # Append one activity sample per tick (from the runner/watchdog snapshot in *tick*), then
        # prune to the same time window as the system samples.
        if tick is not None:
            self._activity_samples.append(self._build_activity_sample(tick, now))
        while self._activity_samples and self._activity_samples[0].time_stamp < cutoff:
            self._activity_samples.popleft()

        # Time axis always spans the full configured window ending at "now" so the charts
        # animate smoothly (the right edge is always the current moment).
        min_ts = now - window_seconds
        max_ts = now
        samples_list = list(self._samples)

        # Commit-charge warning: evaluate the latest sample against the configured threshold. The warning
        # latches — once raised it stays (banner + orange Commit chart) until the user clicks "Clear", so
        # a transient spike that has already dropped back below the threshold is not missed.
        latest = samples_list[-1] if samples_list else None
        if latest is not None and commit_warning_active(latest.commit_percent, latest.commit_total_gb, get_pref().commit_warning_threshold):
            self._commit_warning_latched = True
            self._commit_warning_label.setText(
                f"⚠ System commit charge near limit ({latest.commit_used_gb:.1f}/{latest.commit_total_gb:.1f} GB, {latest.commit_percent:.0f}%)"
                " — risk of paging-file failures / crashed workers."
            )
        commit_warn = self._commit_warning_latched
        self._commit_warning_widget.setVisible(commit_warn)

        self._cpu_chart.update_data(samples_list, min_ts, max_ts)
        self._memory_chart.update_data(samples_list, min_ts, max_ts)
        self._commit_chart.update_data(samples_list, min_ts, max_ts, warn=commit_warn)
        self._disk_chart.update_data(samples_list, min_ts, max_ts)
        self._network_chart.update_data(samples_list, min_ts, max_ts)

        activity_list = list(self._activity_samples)
        activity_stalled = bool(activity_list and activity_list[-1].stalled)
        self._activity_chart.update_data(activity_list, min_ts, max_ts, warn=activity_stalled)

    def _clear_commit_warning(self) -> None:
        """Dismiss the latched commit-charge warning (banner + orange Commit chart).

        The latch re-arms on the next tick whose sample is still over the threshold, so clearing while
        the commit charge remains high simply re-raises it — the button is meant for acknowledging a
        spike that has already subsided.
        """
        self._commit_warning_latched = False
        self._commit_warning_widget.setVisible(False)
        self._commit_chart.clear_warn()

    @staticmethod
    def _build_activity_sample(tick: TickData, now: float) -> "_ActivitySample":
        """Build one :class:`_ActivitySample` from a GUI tick.

        Running count is DB-derived (RUNNING state); idle count and the stalled flag come from the
        stall watchdog's latest :class:`StallInfo` (``tick.stall_info``), published each tick while a
        run is active and stall detection is enabled. When there is no watchdog data the sample is
        simply ``idle == 0`` and not stalled.
        """
        running = sum(1 for rs in tick.run_states.values() if rs.get_state() == PytestRunnerState.RUNNING)
        stall_info = tick.stall_info
        idle = len(getattr(stall_info, "idle_pids", []) or []) if stall_info is not None else 0
        stalled = bool(getattr(stall_info, "stalled", False)) if stall_info is not None else False
        return _ActivitySample(time_stamp=now, running=running, idle=min(idle, running), stalled=stalled)
