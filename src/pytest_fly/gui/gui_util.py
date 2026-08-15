"""
Shared GUI utility functions and widgets.

Provides font/text measurement helpers, data-grouping utilities, and
reusable widgets used across multiple tabs.
"""

import time
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

import humanize
from PySide6.QtCore import QByteArray, QSize
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPalette
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QSizePolicy, QSplitter, QTableWidgetItem, QWidget
from typeguard import typechecked

from ..colors import WARNING_ACCENT
from ..interfaces import PytestProcessInfo
from ..logger import get_logger
from ..preferences import get_pref
from ..pytest_runner.const import BYTES_PER_GB, BYTES_PER_MB
from ..pytest_runner.live_output import read_live_output

# Re-exports: these pure record-transformation helpers moved to tick_data (Qt-free, next to
# the TickData they feed); GUI modules historically import them from here.
from ..tick_data import compute_average_parallelism as compute_average_parallelism
from ..tick_data import compute_time_window as compute_time_window
from ..tick_data import count_test_states as count_test_states
from ..tick_data import extract_test_duration as extract_test_duration
from ..tick_data import first_start_timestamp as first_start_timestamp
from ..tick_data import group_process_infos_by_name as group_process_infos_by_name

log = get_logger()


@lru_cache(maxsize=None)
def get_font(size: int | None = None) -> QFont:
    """Return the shared monospace bold font, optionally at *size* points."""
    font = QFont("Monospace")
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    font.setBold(True)
    if size is not None:
        font.setPointSize(size)
    assert font.styleHint() == QFont.StyleHint.Monospace
    assert font.fixedPitch()
    return font


@lru_cache(maxsize=1000)
def get_text_dimensions(text: str, pad: bool = False, size: int | None = None) -> QSize:
    """
    Determine the dimensions of the provided text

    :param text: The text to measure
    :param pad: Whether to add padding to the text
    :param size: Optional point size; when omitted, uses the default monospace font size.
    :return: The size of the text
    """
    font = get_font(size)
    metrics = QFontMetrics(font)
    text_size = metrics.size(0, text)  # Get the size of the text (QSize)
    if pad:
        single_character_size = metrics.size(0, "X")
        text_size.setWidth(text_size.width() + single_character_size.width())
        text_size.setHeight(text_size.height() + single_character_size.height())
    return text_size


class PlainTextWidget(QPlainTextEdit):
    """Read-only plain-text widget that auto-resizes when its content changes."""

    def __init__(self, parent, initial_text: str):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.MinimumExpanding)
        self._last_text: str | None = None
        self.set_text(initial_text)

    def set_text(self, text: str):
        """Replace the displayed text and resize to fit content without wrapping."""
        if text == self._last_text:
            return
        self._last_text = text
        self.setPlainText(text)
        # Calculate the width needed to display the longest line
        doc = self.document()
        margins = self.contentsMargins()
        doc_margin = int(doc.documentMargin())
        max_line_width = 0
        block = doc.begin()
        while block.isValid():
            line_width = self.fontMetrics().horizontalAdvance(block.text())
            max_line_width = max(max_line_width, line_width)
            block = block.next()
        # Add margins and scrollbar space
        total_width = max_line_width + margins.left() + margins.right() + 2 * doc_margin + 10
        line_count = doc.blockCount()
        line_height = self.fontMetrics().lineSpacing()
        total_height = line_count * line_height + margins.top() + margins.bottom() + 2 * doc_margin
        self.setMinimumWidth(total_width)
        self.setMinimumHeight(total_height)
        self.updateGeometry()


class PhaseTimer:
    """Record elapsed wall-clock time (milliseconds) for named phases of a single operation.

    Usage::

        timer = PhaseTimer()
        with timer.time("db_query"):
            ...
        with timer.time("build"):
            ...
        log.info(timer.format())  # "db_query=18.1 build=9.3"

    Durations are stored in insertion order so the formatted output is stable.
    """

    def __init__(self) -> None:
        self.phases: dict[str, float] = {}
        self._current_name: str | None = None
        self._current_start: float | None = None

    def time(self, name: str) -> "PhaseTimer":
        """Name the next timed phase; use as ``with timer.time("phase"):``."""
        self._current_name = name
        return self

    def __enter__(self) -> "PhaseTimer":
        """Start timing the phase named via :meth:`time`."""
        self._current_start = time.perf_counter()
        return self

    def __exit__(self, *_exc) -> None:
        """Record the elapsed milliseconds for the current phase."""
        assert self._current_name is not None and self._current_start is not None
        self.phases[self._current_name] = (time.perf_counter() - self._current_start) * 1000.0
        self._current_name = None
        self._current_start = None

    def format(self) -> str:
        """Render all recorded phases as ``"name=ms"`` pairs in insertion order."""
        return " ".join(f"{name}={ms:.1f}" for name, ms in self.phases.items())


def resolve_test_output(infos: list[PytestProcessInfo] | None, data_dir: Path, name: str) -> str:
    """
    Return the full captured pytest output for a test.

    Prefers the latest completed ``PytestProcessInfo.output`` record; if none has
    output yet (e.g. the test is still running), falls back to the live-log tail on disk.

    :param infos: This test's process-info records, oldest-first (may be ``None``/empty).
    :param data_dir: pytest-fly data directory holding the live-output logs.
    :param name: Test node id.
    :return: The output text, or an empty string if nothing is available yet.
    """
    for info in reversed(infos or []):
        if info.output:
            return info.output
    return read_live_output(data_dir, name, max_bytes=10_000_000) or ""


def format_runtime(seconds: float) -> str:
    """
    Format a duration in seconds into a human-readable string using ``humanize.precisedelta``.

    :param seconds: Duration in seconds.
    :return: Formatted string (e.g. ``"3 seconds"``, ``"2 minutes and 15 seconds"``).
    """
    return humanize.precisedelta(timedelta(seconds=seconds))


def window_text_color(widget: QWidget) -> QColor:
    """Return the palette's foreground text color for *widget* (respects light/dark themes)."""
    return widget.palette().color(QPalette.ColorRole.WindowText)


def qt_state_to_hex(state: QByteArray) -> str:
    """Serialize a Qt ``saveState()``/``saveGeometry()`` blob to a hex string for preference storage."""
    return state.toHex().data().decode("ascii")


def qt_state_from_hex(hex_text: str) -> QByteArray | None:
    """Deserialize a hex string produced by :func:`qt_state_to_hex`; ``None`` when empty/malformed."""
    if not hex_text:
        return None
    try:
        return QByteArray.fromHex(hex_text.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as e:
        log.debug(f"could not decode stored Qt state: {e}")
        return None


def bind_splitter_to_pref(splitter: QSplitter, pref_name: str) -> None:
    """Restore a splitter's saved divider position and persist it on every user drag.

    The position is stored hex-encoded in the :class:`FlyPreferences` attribute named
    *pref_name*, mirroring the window-geometry persistence.
    """
    saved = qt_state_from_hex(getattr(get_pref(), pref_name))
    if saved is not None:
        splitter.restoreState(saved)
    splitter.splitterMoved.connect(lambda *_unused_args: setattr(get_pref(), pref_name, qt_state_to_hex(splitter.saveState())))


def set_banner(label: QLabel, text: str, color: QColor | None = None, bold: bool = True) -> None:
    """Show *label* as a colored banner with *text* (warning-accent colored by default)."""
    accent = color if color is not None else WARNING_ACCENT
    label.setText(text)
    label.setStyleSheet(f"color: {accent.name()};" + (" font-weight: bold;" if bold else ""))
    label.setVisible(True)


def apply_graph_font(widget: QWidget) -> int:
    """Apply the user's graph-font-size preference to *widget* and return the size in points."""
    size = get_pref().graph_font_size
    widget.setFont(get_font(size=size))
    return size


def format_commit(commit_bytes: int | None) -> str:
    """Format a commit-charge byte count for display — GB at/above 1 GiB, else MB."""
    if commit_bytes is None:
        return ""
    if commit_bytes >= BYTES_PER_GB:
        return f"{commit_bytes / BYTES_PER_GB:.2f} GB"
    return f"{commit_bytes / BYTES_PER_MB:.0f} MB"


def set_utilization_color(item: QTableWidgetItem, value: float, high_threshold: float, low_threshold: float):
    """
    Colorize a table cell based on utilization thresholds.

    Red if above the high threshold, yellow if above the low threshold,
    otherwise the default foreground is restored (important for in-place
    updates where a previously-colored item may drop back below threshold).

    :param item: The table-widget item to colorize.
    :param value: Utilization value in the range ``[0.0, 1.0]``.
    :param high_threshold: Utilization threshold above which the cell is red.
    :param low_threshold: Utilization threshold above which the cell is yellow.
    """
    if value > high_threshold:
        item.setForeground(QColor("red"))
    elif value > low_threshold:
        item.setForeground(QColor("yellow"))
    else:
        item.setForeground(QBrush())


# Per-line width cap. Pytest tracebacks and captured-output lines are often 200+ chars
# wide, which makes Qt's tooltip balloon stretch off-screen. Truncate to a readable width.
_TOOLTIP_WIDTH_LIMIT = 120


@typechecked()
def tool_tip_limiter(text: str | None, line_limit: int | None = None, width_limit: int = _TOOLTIP_WIDTH_LIMIT) -> str:
    """
    Prepare tooltip text from pytest output: keep the last *line_limit* lines
    (falling back to the user preference) and truncate any individual lines longer
    than *width_limit* characters. Applied identically to PASS and FAIL output —
    for a FAIL run the tail naturally contains the FAILURES section and short
    summary; for a PASS run it contains the session summary.

    :param text: The original tooltip text
    :param line_limit: Max lines to show; if None, reads from user preferences
    :param width_limit: Max characters per line before ellipsizing
    :return: The limited tooltip text
    """
    if text is None:
        return ""
    if line_limit is None:
        line_limit = get_pref().tooltip_line_limit

    lines = text.splitlines()
    # Trailing whitespace-only lines would otherwise dominate the tooltip — stripping them
    # here keeps the line-limit budget spent on meaningful content.
    while lines and not lines[-1].strip():
        lines.pop()

    truncated = len(lines) > line_limit
    if truncated:
        lines = lines[-line_limit:]

    if width_limit > 3:
        lines = [line if len(line) <= width_limit else line[: width_limit - 3] + "..." for line in lines]

    body = "\n".join(lines)
    return "...\n" + body if truncated else body
