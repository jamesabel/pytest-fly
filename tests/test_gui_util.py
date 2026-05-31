"""Tests for :mod:`pytest_fly.gui.gui_util`."""

import time

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

from pytest_fly.gui.gui_main import build_tick_data
from pytest_fly.gui.gui_util import (
    PhaseTimer,
    PlainTextWidget,
    compute_average_parallelism,
    compute_time_window,
    count_test_states,
    extract_test_duration,
    format_runtime,
    get_font,
    get_text_dimensions,
    group_process_infos_by_name,
    tool_tip_limiter,
    window_text_color,
)
from pytest_fly.interfaces import PyTestFlyExitCode, PytestProcessInfo


def _info(name, pid, exit_code, time_stamp):
    """Minimal PytestProcessInfo for a single observation of a test."""
    return PytestProcessInfo(run_guid="g", name=name, pid=pid, exit_code=exit_code, output=None, time_stamp=time_stamp)


# ---------------------------------------------------------------------------
# group_process_infos_by_name
# ---------------------------------------------------------------------------


def test_group_process_infos_by_name_empty():
    assert group_process_infos_by_name([]) == {}


def test_group_process_infos_by_name_groups_in_order():
    infos = [
        _info("a", None, PyTestFlyExitCode.NONE, 1.0),
        _info("b", None, PyTestFlyExitCode.NONE, 2.0),
        _info("a", 10, PyTestFlyExitCode.NONE, 3.0),
    ]
    grouped = group_process_infos_by_name(infos)
    assert list(grouped) == ["a", "b"]
    assert [i.time_stamp for i in grouped["a"]] == [1.0, 3.0]


# ---------------------------------------------------------------------------
# compute_time_window
# ---------------------------------------------------------------------------


def test_compute_time_window_empty():
    assert compute_time_window([]) == (None, None)


def test_compute_time_window_min_max():
    infos = [
        _info("a", 1, PyTestFlyExitCode.NONE, 5.0),
        _info("a", 1, PyTestFlyExitCode.NONE, 2.0),
        _info("a", 1, PyTestFlyExitCode.NONE, 9.0),
    ]
    assert compute_time_window(infos) == (2.0, 9.0)


def test_compute_time_window_require_pid_skips_unstarted():
    infos = [
        _info("a", None, PyTestFlyExitCode.NONE, 1.0),  # not started — ignored when require_pid
        _info("a", 1, PyTestFlyExitCode.NONE, 4.0),
        _info("a", 1, PyTestFlyExitCode.NONE, 7.0),
    ]
    assert compute_time_window(infos, require_pid=True) == (4.0, 7.0)


# ---------------------------------------------------------------------------
# format_runtime
# ---------------------------------------------------------------------------


def test_format_runtime_seconds():
    assert "second" in format_runtime(3)


def test_format_runtime_minutes():
    result = format_runtime(135)
    assert "minute" in result and "second" in result


# ---------------------------------------------------------------------------
# extract_test_duration
# ---------------------------------------------------------------------------


def test_extract_test_duration_start_and_end():
    infos = [
        _info("a", None, PyTestFlyExitCode.NONE, 1.0),  # queued
        _info("a", 10, PyTestFlyExitCode.NONE, 2.0),  # started
        _info("a", 10, PyTestFlyExitCode.OK, 5.0),  # finished
    ]
    assert extract_test_duration(infos) == (2.0, 5.0)


def test_extract_test_duration_never_started():
    infos = [_info("a", None, PyTestFlyExitCode.NONE, 1.0)]
    assert extract_test_duration(infos) == (None, None)


# ---------------------------------------------------------------------------
# compute_average_parallelism
# ---------------------------------------------------------------------------


def test_compute_average_parallelism_serial_is_one():
    infos_by_name = {"a": [_info("a", 1, PyTestFlyExitCode.NONE, 0.0), _info("a", 1, PyTestFlyExitCode.OK, 10.0)]}
    assert compute_average_parallelism(infos_by_name) == 1.0


def test_compute_average_parallelism_overlap_above_one():
    # Two tests each running 0..10 (fully overlapping): total 20s over 10s wall = 2.0.
    infos_by_name = {
        "a": [_info("a", 1, PyTestFlyExitCode.NONE, 0.0), _info("a", 1, PyTestFlyExitCode.OK, 10.0)],
        "b": [_info("b", 2, PyTestFlyExitCode.NONE, 0.0), _info("b", 2, PyTestFlyExitCode.OK, 10.0)],
    }
    assert compute_average_parallelism(infos_by_name) == 2.0


def test_compute_average_parallelism_running_uses_now():
    # A still-running test (no terminal exit code) contributes up to "now".
    start = time.time() - 5.0
    infos_by_name = {"a": [_info("a", 1, PyTestFlyExitCode.NONE, start)]}
    result = compute_average_parallelism(infos_by_name)
    assert result is not None and result > 0.0


def test_compute_average_parallelism_empty_is_none():
    assert compute_average_parallelism({}) is None


def test_compute_average_parallelism_zero_wall_is_none():
    # A single instantaneous record: start == end -> zero wall clock -> None.
    infos_by_name = {"a": [_info("a", 1, PyTestFlyExitCode.OK, 5.0)]}
    assert compute_average_parallelism(infos_by_name) is None


# ---------------------------------------------------------------------------
# count_test_states
# ---------------------------------------------------------------------------


def test_count_test_states():
    now = time.time()
    infos = [
        _info("pass", 1, PyTestFlyExitCode.NONE, now),
        _info("pass", 1, PyTestFlyExitCode.OK, now + 1),
        _info("fail", 2, PyTestFlyExitCode.NONE, now),
        _info("fail", 2, PyTestFlyExitCode.TESTS_FAILED, now + 1),
        _info("queued", None, PyTestFlyExitCode.NONE, now),
    ]
    tick = build_tick_data(infos)
    counts = count_test_states(tick.run_states)
    # Exactly three tests, one in each terminal/queued state.
    assert sum(counts.values()) == 3
    assert max(counts.values()) == 1


# ---------------------------------------------------------------------------
# PhaseTimer
# ---------------------------------------------------------------------------


def test_phase_timer_records_phases_in_order():
    timer = PhaseTimer()
    with timer.time("first"):
        pass
    with timer.time("second"):
        pass
    assert list(timer.phases) == ["first", "second"]
    formatted = timer.format()
    assert formatted.startswith("first=")
    assert "second=" in formatted


# ---------------------------------------------------------------------------
# tool_tip_limiter
# ---------------------------------------------------------------------------


def test_tool_tip_limiter_none():
    assert tool_tip_limiter(None) == ""


def test_tool_tip_limiter_strips_trailing_blank_lines():
    assert tool_tip_limiter("body\n\n  \n", line_limit=10) == "body"


def test_tool_tip_limiter_keeps_tail_with_marker():
    text = "\n".join(f"line{n}" for n in range(10))
    result = tool_tip_limiter(text, line_limit=3)
    assert result.startswith("...\n")
    assert result.endswith("line9")
    assert "line0" not in result


def test_tool_tip_limiter_truncates_wide_lines():
    long_line = "x" * 200
    result = tool_tip_limiter(long_line, line_limit=10, width_limit=50)
    assert result.endswith("...")
    assert len(result) == 50


def test_tool_tip_limiter_uses_preference_default():
    # line_limit=None reads get_pref().tooltip_line_limit (bound to tmp prefs in conftest).
    text = "\n".join(f"line{n}" for n in range(500))
    result = tool_tip_limiter(text)
    # Whatever the preference is, the result must be a non-empty bounded tail.
    assert result
    assert len(result.splitlines()) <= 500


# ---------------------------------------------------------------------------
# Qt-dependent helpers
# ---------------------------------------------------------------------------


def test_get_font_is_cached_and_sizable(app):
    assert get_font() is get_font()  # lru_cache returns the same object
    sized = get_font(14)
    assert sized.pointSize() == 14


def test_get_text_dimensions_pad_is_larger(app):
    plain = get_text_dimensions("hello")
    padded = get_text_dimensions("hello", pad=True)
    assert padded.width() > plain.width()
    assert padded.height() > plain.height()


def test_window_text_color_returns_qcolor(app):
    widget = QWidget()
    assert isinstance(window_text_color(widget), QColor)


def test_plain_text_widget_set_text(app):
    widget = PlainTextWidget(None, "initial")
    assert widget.toPlainText() == "initial"
    widget.set_text("changed")
    assert widget.toPlainText() == "changed"
    # Setting the same text again is a no-op (does not raise, content stable).
    widget.set_text("changed")
    assert widget.toPlainText() == "changed"
