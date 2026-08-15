"""
Coverage tab — displays a step-function line chart of combined code coverage over time.
"""

from pathlib import Path

from coverage.exceptions import CoverageException
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QMessageBox, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ...colors import COVERAGE_FILL_COLOR, COVERAGE_LINE_COLOR
from ...interfaces import PytestRunnerState
from ...logger import get_logger
from ...pytest_runner.coverage import calculate_coverage
from ...tick_data import TickData
from ..charts import paint_chart_frame
from ..graph_tab.time_axis import Y_GRID_PCTS, TimeAxisMapping
from ..gui_util import count_test_states, get_text_dimensions, window_text_color
from ..view_coverage import ViewCoverage

log = get_logger()

# Test identifier used when generating the on-demand HTML report.  Kept distinct from
# the live tracker's "current" identifier so clicking the button never races with the
# periodic coverage recalculation writing to the same combined data file.
_HTML_REPORT_IDENTIFIER = "html_report"


class _CoverageChart(QWidget):
    """Custom-painted widget that renders a coverage-over-time step chart."""

    def __init__(self):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._coverage_history: list[tuple[float, float]] = []
        self._min_ts: float | None = None
        self._max_ts: float | None = None
        self._status_text: str = ""
        self._covered_lines: int = 0
        self._total_lines: int = 0

    def update_data(self, coverage_history: list[tuple[float, float]], min_ts: float | None, max_ts: float | None, status_text: str, covered_lines: int = 0, total_lines: int = 0):
        self._coverage_history = coverage_history
        self._min_ts = min_ts
        self._max_ts = max_ts
        self._status_text = status_text
        self._covered_lines = covered_lines
        self._total_lines = total_lines
        self.update()

    def paintEvent(self, event):
        """Paint the shared chart frame, the x-axis time labels, and the coverage step line."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        h = self.height()
        frame = paint_chart_frame(
            painter,
            self,
            y_ticks=[(pct, f"{int(pct * 100)}%") for pct in Y_GRID_PCTS],
            min_ts=self._min_ts,
            max_ts=self._max_ts,
            margin_left=get_text_dimensions("100% ").width(),
            margin_top=get_text_dimensions("X").height() + 8,  # room for coverage label and status
            margin_bottom=get_text_dimensions("X").height() + 4,
        )
        if frame is None:
            painter.end()
            return
        margin_left = frame.margin_left
        margin_top = frame.margin_top
        chart_w = frame.chart_w
        chart_h = frame.chart_h
        w = self.width()

        text_color = window_text_color(self)

        # X-axis time labels under the vertical grid lines the frame painter drew.
        painter.setPen(QPen(text_color, 1))
        for x, label in frame.grid_ticks:
            painter.drawText(int(margin_left + x) - 8, h - 2, label)

        # Draw status indicator
        if self._status_text:
            painter.setPen(QPen(text_color, 1))
            status_x = w - get_text_dimensions(self._status_text).width() - 10
            painter.drawText(status_x, get_text_dimensions("X").height(), self._status_text)

        # Draw coverage step line
        if not self._coverage_history or self._min_ts is None or self._max_ts is None:
            painter.setPen(QPen(text_color, 1))
            painter.drawText(margin_left + 10, margin_top + chart_h // 2, "Waiting for coverage data...")
            painter.end()
            return

        mapping = TimeAxisMapping(min_ts=self._min_ts, max_ts=self._max_ts, width_pixels=chart_w)

        def to_pixel(ts: float, pct: float) -> tuple[int, int]:
            x = margin_left + int(mapping.ts_to_x(ts))
            y = margin_top + int(chart_h * (1.0 - pct))
            return x, y

        # Build step-function points
        points = []
        for i, (ts, pct) in enumerate(self._coverage_history):
            x, y = to_pixel(ts, pct)
            if i > 0:
                # horizontal step from previous y to current x
                points.append((x, points[-1][1]))
            points.append((x, y))

        # Draw filled area under the line
        if len(points) >= 2:
            fill_points = [QPointF(px, py) for px, py in points]
            # close the polygon along the bottom
            fill_points.append(QPointF(points[-1][0], margin_top + chart_h))
            fill_points.append(QPointF(points[0][0], margin_top + chart_h))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(COVERAGE_FILL_COLOR))
            painter.drawPolygon(QPolygonF(fill_points))

        # Draw the line itself
        painter.setPen(QPen(COVERAGE_LINE_COLOR, 2))
        for i in range(len(points) - 1):
            painter.drawLine(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1])

        # Draw current coverage label with line counts and note
        latest_pct = self._coverage_history[-1][1]
        label = f"Coverage: {latest_pct:.1%}"
        if self._total_lines > 0:
            label += f"  ({self._covered_lines}/{self._total_lines} lines)"
        label += "    (line count may increase as tests discover new source files)"
        painter.setPen(QPen(text_color, 1))
        char_h = get_text_dimensions("X").height()
        painter.drawText(margin_left + 10, char_h, label)

        painter.end()


class CoverageTab(QGroupBox):
    """Tab displaying a line chart of combined code coverage over time.

    :param data_dir: Application data directory.  When provided, a "View HTML Report"
        button is shown that generates and opens the detailed line-by-line coverage
        report.  When ``None`` (e.g. in isolated widget tests) the button is omitted.
    """

    def __init__(self, data_dir: Path | None = None):
        super().__init__()
        self.setTitle("Coverage")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._data_dir = data_dir

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.view_report_button: QPushButton | None = None
        if data_dir is not None:
            button_row = QHBoxLayout()
            button_row.addStretch()
            self.view_report_button = QPushButton("View HTML Report")
            self.view_report_button.setToolTip("Generate and open the detailed line-by-line HTML coverage report in your browser.")
            self.view_report_button.setEnabled(False)  # enabled once there is coverage data to report
            self.view_report_button.clicked.connect(self._on_view_report)
            button_row.addWidget(self.view_report_button)
            layout.addLayout(button_row)

        self.chart = _CoverageChart()
        layout.addWidget(self.chart, stretch=1)

    def _on_view_report(self) -> None:
        """Generate a fresh HTML coverage report from the current data and open it.

        Failures are shown to the user (a warning dialog), not just logged — previously a
        failed generation silently opened a stale report, and a missing report opened nothing.
        """
        if self._data_dir is None:
            return
        try:
            calculate_coverage(_HTML_REPORT_IDENTIFIER, self._data_dir, write_report=True)
        except (OSError, ValueError, CoverageException) as e:
            log.warning(f"HTML coverage report generation failed: {e}")
            QMessageBox.warning(self, "Coverage report", f"Could not generate the HTML coverage report:\n{e}")
            return
        if not ViewCoverage(self._data_dir).view():
            QMessageBox.warning(self, "Coverage report", "No HTML coverage report was found to open.")

    def update_tick(self, tick: TickData) -> None:
        """Refresh the coverage chart and the report button from pre-computed tick data."""
        # Compute status indicator from run states
        if tick.run_states:
            total = len(tick.run_states)
            counts = count_test_states(tick.run_states)
            running = counts[PytestRunnerState.RUNNING]
            queued = counts[PytestRunnerState.QUEUED]
            if running > 0 or queued > 0:
                completed = total - running - queued
                status_text = f"Running ({completed}/{total} complete)"
            else:
                status_text = f"Complete ({total}/{total} tests)"
        else:
            status_text = ""

        self.chart.update_data(tick.coverage_history, tick.effective_min_time_stamp, tick.max_time_stamp, status_text, tick.covered_lines, tick.total_lines)

        # Only offer the report once there is coverage data to render.
        if self.view_report_button is not None:
            self.view_report_button.setEnabled(tick.total_lines > 0)
