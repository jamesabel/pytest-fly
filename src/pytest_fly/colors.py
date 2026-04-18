"""
Centralized color definitions for test-state visualization.

Bar colors are used on the graph-tab progress bars; table colors are used in the
text of the table-tab status column.  Grid and chart colors are shared across
the graph and coverage tabs.  Keeping them in one place makes it easy to adjust
the palette without hunting through multiple modules.
"""

from PySide6.QtGui import QColor

from .interfaces import PytestRunnerState

# Colors used for the progress-bar rectangles on the Graph tab.
BAR_COLORS: dict[PytestRunnerState, QColor] = {
    PytestRunnerState.QUEUED: QColor("blue"),
    PytestRunnerState.RUNNING: QColor("lightgray"),
    PytestRunnerState.PASS: QColor("lightgreen"),
    PytestRunnerState.FAIL: QColor("red"),
    PytestRunnerState.TERMINATED: QColor("orange"),
    PytestRunnerState.STOPPED: QColor("gray"),
}

# Colors used for the foreground text on the Table tab.
TABLE_COLORS: dict[PytestRunnerState, QColor] = {
    PytestRunnerState.QUEUED: QColor("blue"),
    PytestRunnerState.RUNNING: QColor("black"),
    PytestRunnerState.PASS: QColor("green"),
    PytestRunnerState.FAIL: QColor("red"),
    PytestRunnerState.TERMINATED: QColor("orange"),
    PytestRunnerState.STOPPED: QColor("gray"),
}

# Grid line color — light gray, semi-transparent so bars and charts remain readable.
# Shared by the graph-tab time axis, progress bars, and the coverage chart.
GRID_LINE_COLOR = QColor(180, 180, 180, 100)

# Coverage chart colors (used on the Coverage tab).
COVERAGE_LINE_COLOR = QColor(34, 139, 34)  # forest green
COVERAGE_FILL_COLOR = QColor(34, 139, 34, 40)  # translucent green fill

# System-metrics chart colors (used on the Run tab's system performance widget).
CPU_LINE_COLOR = QColor(220, 20, 60)  # crimson
MEMORY_LINE_COLOR = QColor(30, 144, 255)  # dodger blue
DISK_READ_COLOR = QColor(255, 140, 0)  # dark orange
DISK_WRITE_COLOR = QColor(148, 0, 211)  # dark violet
NET_SENT_COLOR = QColor(34, 139, 34)  # forest green
NET_RECV_COLOR = QColor(64, 224, 208)  # turquoise
