"""
Centralized color definitions for test-state visualization.

Bar colors are used on the graph-tab progress bars; table colors are used in the
text of the table-tab status column.  Keeping them in one place makes it easy to
adjust the palette without hunting through multiple modules.
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
}

# Colors used for the foreground text on the Table tab.
TABLE_COLORS: dict[PytestRunnerState, QColor] = {
    PytestRunnerState.QUEUED: QColor("blue"),
    PytestRunnerState.RUNNING: QColor("black"),
    PytestRunnerState.PASS: QColor("green"),
    PytestRunnerState.FAIL: QColor("red"),
    PytestRunnerState.TERMINATED: QColor("orange"),
}
