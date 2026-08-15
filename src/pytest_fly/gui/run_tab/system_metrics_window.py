"""
Run-tab system-performance widget — a grid of charts of system-wide CPU, memory,
commit charge, disk I/O, network I/O, and test activity, sampled by
:class:`SystemMonitor` in a separate process.

The widget keeps a time-pruned ring buffer of :class:`SystemMonitorSample` records
and repaints from that buffer.  Sampling runs in a subprocess (owned by the main
window), so the GUI thread only does a non-blocking queue drain + a `QPainter`
repaint per tick.

Chart style follows ``coverage_tab._CoverageChart`` — custom ``QPainter`` with
``TimeAxisMapping`` + ``compute_grid_ticks`` from the graph-tab time-axis module.
"""

import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from ...colors import (
    COMMIT_LINE_COLOR,
    CPU_LINE_COLOR,
    DISK_READ_COLOR,
    DISK_WRITE_COLOR,
    MEMORY_LINE_COLOR,
    NET_RECV_COLOR,
    NET_SENT_COLOR,
    WARNING_ACCENT,
)
from ...interfaces import PytestRunnerState
from ...preferences import get_pref
from ...pytest_runner.commit_memory import PageFileInfo, commit_warning_active, pagefile_breakdown
from ...pytest_runner.system_monitor import SystemMonitorSample
from ...tick_data import TickData
from ..charts import MetricChart, Series

# Activity-chart line colors: tests that are running vs. those sampled idle (near-zero CPU).
ACTIVITY_RUNNING_COLOR = QColor("#2e7d32")  # green
ACTIVITY_IDLE_COLOR = WARNING_ACCENT  # amber (the shared warning accent)


@dataclass(frozen=True)
class _ActivitySample:
    """One time-stamped snapshot of in-flight test activity for the Activity chart."""

    time_stamp: float
    running: int  # tests in the RUNNING state
    idle: int  # running tests whose subtree CPU is below the idle epsilon
    stalled: bool  # the watchdog has flagged the run as stalled


class SystemMetricsWindow(QGroupBox):
    """Container panel with six sub-charts in a grid (CPU, Memory, Commit, Disk, Network, Activity)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("System Performance")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QGridLayout()
        self.setLayout(layout)

        self._cpu_chart = MetricChart(
            title="CPU",
            series=[Series(label="usage", color=CPU_LINE_COLOR, getter=lambda s: s.cpu_percent)],
            unit="%",
            y_max_fixed=100.0,
        )
        self._memory_chart = MetricChart(
            title="Memory",
            series=[
                Series(
                    label="usage",
                    color=MEMORY_LINE_COLOR,
                    getter=lambda s: s.memory_percent,
                    legend_formatter=lambda s: f"{s.memory_used_gb:.1f}/{s.memory_total_gb:.1f} GB ({s.memory_percent:.0f}%)",
                )
            ],
            unit="%",
            y_max_fixed=100.0,
        )
        self._commit_chart = MetricChart(
            title="Commit",
            series=[
                Series(
                    label="charge",
                    color=COMMIT_LINE_COLOR,
                    getter=lambda s: s.commit_percent,
                    legend_formatter=lambda s: "N/A" if s.commit_total_gb <= 0 else f"{s.commit_used_gb:.1f}/{s.commit_total_gb:.1f} GB ({s.commit_percent:.0f}%)",
                )
            ],
            unit="%",
            y_max_fixed=100.0,
        )
        self._disk_chart = MetricChart(
            title="Disk",
            series=[
                Series(label="read", color=DISK_READ_COLOR, getter=lambda s: s.disk_read_mbps),
                Series(label="write", color=DISK_WRITE_COLOR, getter=lambda s: s.disk_write_mbps),
            ],
            unit="MB/s",
            y_max_fixed=None,
        )
        self._network_chart = MetricChart(
            title="Network",
            series=[
                Series(label="sent", color=NET_SENT_COLOR, getter=lambda s: s.net_sent_mbps),
                Series(label="recv", color=NET_RECV_COLOR, getter=lambda s: s.net_recv_mbps),
            ],
            unit="MB/s",
            y_max_fixed=None,
        )

        # Test-activity chart — running vs. idle in-flight test counts over time. Plotted like the
        # other charts so a wedge is visible at a glance (idle climbs to meet running). Lines turn
        # warning-colored while the stall watchdog has the run flagged as stalled.
        self._activity_chart = MetricChart(
            title="Activity",
            series=[
                Series(label="running", color=ACTIVITY_RUNNING_COLOR, getter=lambda s: float(s.running), legend_formatter=lambda s: str(s.running)),
                Series(label="idle", color=ACTIVITY_IDLE_COLOR, getter=lambda s: float(s.idle), legend_formatter=lambda s: str(s.idle)),
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

        # Commit status line — always visible beneath the chart grid (spans the full width so it never
        # steals a chart cell). It shows the all-time peak commit charge and the pagefile breakdown
        # (the discs + sizes that, with physical RAM, make up the commit limit). When the commit charge
        # crosses the configured threshold the warning latches: it is prepended in orange and the Commit
        # chart turns orange, and both hold (even after a transient spike subsides) until the user resets.
        self._samples: deque[SystemMonitorSample] = deque()
        self._activity_samples: deque[_ActivitySample] = deque()

        self._commit_warning_latched = False
        # All-time peak commit charge, tracked across the whole run (not just the visible window) and
        # held until reset. 0.0 total means "no commit signal yet / unavailable".
        self._commit_peak_percent = 0.0
        self._commit_peak_used_gb = 0.0
        self._commit_peak_total_gb = 0.0
        # Configured pagefiles — read once (a cheap registry read) and refreshed on reset.
        self._pagefiles: list[PageFileInfo] = pagefile_breakdown()

        self._commit_status_label = QLabel("")
        self._commit_status_label.setWordWrap(False)  # keep the status to a single line
        self._commit_status_label.setTextFormat(Qt.TextFormat.RichText)

        self._commit_reset_button = QPushButton("Reset")
        self._commit_reset_button.setToolTip("Reset the all-time peak commit charge, refresh the pagefile breakdown, and clear any commit-charge warning.")
        self._commit_reset_button.clicked.connect(self._reset_commit_stats)

        self._commit_status_widget = QWidget()
        status_layout = QHBoxLayout(self._commit_status_widget)
        status_layout.setContentsMargins(0, 0, 0, 0)
        # Status text takes only its natural width and the "Reset" button sits directly after it (a
        # trailing stretch absorbs the remaining space), so the button stays next to the text rather
        # than drifting to the far right edge where it is easy to miss.
        status_layout.addWidget(self._commit_status_label, 0)
        status_layout.addWidget(self._commit_reset_button, 0)
        status_layout.addStretch(1)
        layout.addWidget(self._commit_status_widget, 3, 0, 1, 2)
        self._refresh_commit_status()

        layout.setRowStretch(0, 1)
        layout.setRowStretch(1, 1)
        layout.setRowStretch(2, 1)
        layout.setRowStretch(3, 0)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)

    def ingest_samples(self, samples: Iterable[SystemMonitorSample]) -> None:
        """Append new samples to the ring buffer (called once per GUI tick).

        The all-time peak commit charge is updated here (not from the pruned window) so it survives
        samples scrolling out of the visible time window; it is only cleared by an explicit reset.
        """
        for sample in samples:
            self._samples.append(sample)
            if sample.commit_total_gb > 0 and sample.commit_percent > self._commit_peak_percent:
                self._commit_peak_percent = sample.commit_percent
                self._commit_peak_used_gb = sample.commit_used_gb
                self._commit_peak_total_gb = sample.commit_total_gb

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
        # latches — once raised it stays (orange status line + orange Commit chart) until the user clicks
        # "Reset", so a transient spike that has already dropped back below the threshold is not missed.
        latest = samples_list[-1] if samples_list else None
        if latest is not None and commit_warning_active(latest.commit_percent, latest.commit_total_gb, get_pref().commit_warning_threshold):
            self._commit_warning_latched = True
        commit_warn = self._commit_warning_latched
        self._refresh_commit_status()

        self._cpu_chart.update_data(samples_list, min_ts, max_ts)
        self._memory_chart.update_data(samples_list, min_ts, max_ts)
        self._commit_chart.update_data(samples_list, min_ts, max_ts, warn=commit_warn)
        self._disk_chart.update_data(samples_list, min_ts, max_ts)
        self._network_chart.update_data(samples_list, min_ts, max_ts)

        activity_list = list(self._activity_samples)
        activity_stalled = bool(activity_list and activity_list[-1].stalled)
        self._activity_chart.update_data(activity_list, min_ts, max_ts, warn=activity_stalled)

    def _reset_commit_stats(self) -> None:
        """Reset the all-time peak commit charge, refresh the pagefile breakdown, and clear the warning.

        The peak is re-seeded from the current sample (so it tracks fresh from "now" rather than
        snapping back to the still-high reading a moment later). The warning latch re-arms on the next
        tick whose sample is still over the threshold, so resetting while the commit charge remains high
        simply re-raises it — the button is meant for acknowledging a spike that has already subsided.
        """
        self._commit_warning_latched = False
        latest = self._samples[-1] if self._samples else None
        if latest is not None and latest.commit_total_gb > 0:
            self._commit_peak_percent = latest.commit_percent
            self._commit_peak_used_gb = latest.commit_used_gb
            self._commit_peak_total_gb = latest.commit_total_gb
        else:
            self._commit_peak_percent = 0.0
            self._commit_peak_used_gb = 0.0
            self._commit_peak_total_gb = 0.0
        self._pagefiles = pagefile_breakdown()
        self._commit_chart.clear_warn()
        self._refresh_commit_status()

    def _refresh_commit_status(self) -> None:
        """Rebuild and display the commit-status line (peak, pagefiles, latched warning)."""
        self._commit_status_label.setText(self._build_commit_status_text())

    def _build_commit_status_text(self) -> str:
        """Build the always-visible commit status line: peak commit charge + pagefile breakdown,
        with the latched warning prepended in orange when active."""
        if self._commit_peak_total_gb > 0:
            peak = f"Peak commit: {self._commit_peak_used_gb:.1f}/{self._commit_peak_total_gb:.1f} GB ({self._commit_peak_percent:.0f}%)"
        else:
            peak = "Peak commit: --"
        parts = [peak, self._pagefile_summary()]
        status = "&nbsp;&nbsp;·&nbsp;&nbsp;".join(parts)

        latest = self._samples[-1] if self._samples else None
        if self._commit_warning_latched and latest is not None:
            warning = (
                f"⚠ System commit charge near limit ({latest.commit_used_gb:.1f}/{latest.commit_total_gb:.1f} GB, {latest.commit_percent:.0f}%)"
                " — risk of paging-file failures / crashed workers."
            )
            # The shared warning accent (matches the status banners and the Commit chart accent).
            # Kept on the same line as the status so the whole strip stays a single row.
            return f'<span style="color: {WARNING_ACCENT.name()};">{warning}</span>&nbsp;&nbsp;·&nbsp;&nbsp;{status}'
        return status

    def _pagefile_summary(self) -> str:
        """Summarize the pagefiles that make up the commit limit: which discs and their sizes, plus the
        live total pagefile (commit limit minus physical RAM, both from the latest sample)."""
        latest = self._samples[-1] if self._samples else None
        total_suffix = ""
        if latest is not None and latest.commit_total_gb > 0 and latest.memory_total_gb > 0:
            total_gb = max(latest.commit_total_gb - latest.memory_total_gb, 0.0)
            total_suffix = f" (total {total_gb:.1f} GB)"

        if not self._pagefiles:
            return "Pagefile: n/a" + total_suffix

        entries = []
        for pf in self._pagefiles:
            if pf.system_managed:
                entries.append(f"{pf.drive} auto")
            else:
                entries.append(f"{pf.drive} {pf.maximum_mb / 1024.0:.1f} GB")
        return "Pagefile: " + ", ".join(entries) + total_suffix

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
