"""
Shared GUI utility functions and widgets.

Provides font/text measurement helpers, data-grouping utilities, and
reusable widgets used across multiple tabs.
"""

import time
from collections import defaultdict
from datetime import timedelta
from functools import lru_cache

import humanize
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPalette
from PySide6.QtWidgets import QPlainTextEdit, QSizePolicy, QWidget
from typeguard import typechecked

from ..interfaces import PytestProcessInfo
from ..preferences import get_pref


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
        self.set_text(initial_text)

    def set_text(self, text: str):
        """Replace the displayed text and resize to fit content without wrapping."""
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
        self._current_name = name
        return self

    def __enter__(self) -> "PhaseTimer":
        self._current_start = time.perf_counter()
        return self

    def __exit__(self, *_exc) -> None:
        assert self._current_name is not None and self._current_start is not None
        self.phases[self._current_name] = (time.perf_counter() - self._current_start) * 1000.0
        self._current_name = None
        self._current_start = None

    def format(self) -> str:
        return " ".join(f"{name}={ms:.1f}" for name, ms in self.phases.items())


def group_process_infos_by_name(process_infos: list[PytestProcessInfo]) -> dict[str, list[PytestProcessInfo]]:
    """
    Group a flat list of process info records by test name.

    :param process_infos: Flat list of ``PytestProcessInfo`` objects.
    :return: Dictionary mapping each test name to its list of info records, in encounter order.
    """
    grouped: dict[str, list[PytestProcessInfo]] = defaultdict(list)
    for info in process_infos:
        grouped[info.name].append(info)
    return grouped


def compute_time_window(process_infos: list[PytestProcessInfo], require_pid: bool = False) -> tuple[float | None, float | None]:
    """
    Compute the minimum and maximum timestamps from a list of process info records.

    :param process_infos: List of ``PytestProcessInfo`` objects.
    :param require_pid: If ``True``, only consider records where ``pid`` is not ``None``
                        (i.e. the process has actually started).
    :return: ``(min_timestamp, max_timestamp)`` tuple, or ``(None, None)`` if no records qualify.
    """
    min_ts: float | None = None
    max_ts: float | None = None
    for info in process_infos:
        if require_pid and info.pid is None:
            continue
        if min_ts is None or info.time_stamp < min_ts:
            min_ts = info.time_stamp
        if max_ts is None or info.time_stamp > max_ts:
            max_ts = info.time_stamp
    return min_ts, max_ts


def format_runtime(seconds: float) -> str:
    """
    Format a duration in seconds into a human-readable string using ``humanize.precisedelta``.

    :param seconds: Duration in seconds.
    :return: Formatted string (e.g. ``"3 seconds"``, ``"2 minutes and 15 seconds"``).
    """
    return humanize.precisedelta(timedelta(seconds=seconds))


def count_test_states(run_states: dict) -> dict:
    """Count tests by their current PytestRunnerState."""
    counts = defaultdict(int)
    for run_state in run_states.values():
        counts[run_state.get_state()] += 1
    return counts


def extract_test_duration(infos: list) -> tuple[float | None, float | None]:
    """
    Extract start and end timestamps from a test's process info records.

    :param infos: List of PytestProcessInfo for a single test.
    :return: (start_timestamp, end_timestamp) or (None, None).
    """
    from ..interfaces import PyTestFlyExitCode

    start = None
    end = None
    for info in infos:
        if info.pid is not None and start is None:
            start = info.time_stamp
        if info.exit_code != PyTestFlyExitCode.NONE:
            end = info.time_stamp
    return start, end


def compute_average_parallelism(infos_by_name: dict[str, list[PytestProcessInfo]]) -> float | None:
    """
    Compute the average number of simultaneously running test processes.

    Average parallelism = total_test_time / wall_clock_time.

    For in-progress tests (started but not finished), the current time is used
    as the end time so the metric updates live during a run.

    :param infos_by_name: Process info records grouped by test name.
    :return: Average parallelism, or ``None`` if insufficient data.
    """
    total_test_time = 0.0
    all_starts: list[float] = []
    all_ends: list[float] = []
    now = time.time()

    for infos in infos_by_name.values():
        start, end = extract_test_duration(infos)
        if start is not None:
            if end is None:
                end = now  # test still running
            total_test_time += end - start
            all_starts.append(start)
            all_ends.append(end)

    if not all_starts:
        return None

    wall_clock = max(all_ends) - min(all_starts)
    if wall_clock <= 0:
        return None

    return total_test_time / wall_clock


def window_text_color(widget: QWidget) -> QColor:
    """Return the palette's foreground text color for *widget* (respects light/dark themes)."""
    return widget.palette().color(QPalette.WindowText)


# Per-line width cap. Pytest tracebacks and captured-output lines are often 200+ chars
# wide, which makes Qt's tooltip balloon stretch off-screen. Truncate to a readable width.
_TOOLTIP_WIDTH_LIMIT = 120


@typechecked
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
