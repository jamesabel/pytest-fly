import time
from collections import defaultdict
from datetime import timedelta
from functools import cache, lru_cache

import humanize
from PySide6.QtCore import QSize
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QPlainTextEdit, QSizePolicy
from typeguard import typechecked

from ..const import TOOLTIP_LINE_LIMIT
from ..interfaces import PytestProcessInfo


@cache
def get_font() -> QFont:
    # monospace font
    font = QFont("Monospace")
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    font.setBold(True)
    assert font.styleHint() == QFont.StyleHint.Monospace
    assert font.fixedPitch()
    return font


@lru_cache(maxsize=1000)
def get_text_dimensions(text: str, pad: bool = False) -> QSize:
    """
    Determine the dimensions of the provided text

    :param text: The text to measure
    :param pad: Whether to add padding to the text
    :return: The size of the text
    """
    font = get_font()
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


@typechecked
def tool_tip_limiter(text: str | None) -> str:
    """
    Limit the number of lines in a tooltip text.

    :param text: The original tooltip text
    :return: The limited tooltip text
    """
    if text is None:
        return ""
    lines = text.splitlines()
    if len(lines) > TOOLTIP_LINE_LIMIT:
        limited_text = "...\n" + "\n".join(lines[len(lines) - TOOLTIP_LINE_LIMIT :])
        return limited_text
    return text
