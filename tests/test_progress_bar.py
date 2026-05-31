"""Paint and interaction coverage for the Graph-tab PytestProgressBar."""

import time

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from pytest_fly.gui.graph_tab.progress_bar import PytestProgressBar
from pytest_fly.interfaces import PyTestFlyExitCode, PytestProcessInfo
from pytest_fly.pytest_runner.pytest_runner import PytestRunState


def _info(name, pid, exit_code, ts, output=None):
    return PytestProcessInfo(run_guid="g", name=name, pid=pid, exit_code=exit_code, output=output, time_stamp=ts)


def test_progress_bar_paints_running(app):
    """A running bar paints a filled rectangle up to 'now'."""
    now = time.time()
    infos = [_info("tests/test_a.py", None, PyTestFlyExitCode.NONE, now - 10), _info("tests/test_a.py", 1, PyTestFlyExitCode.NONE, now - 9)]
    bar = PytestProgressBar(infos, now - 10, now, PytestRunState(infos))
    bar.resize(400, 20)
    bar.grab()
    assert bar._last_bar_rect is not None  # a bar was drawn


def test_progress_bar_paints_completed_singleton(app):
    """A completed singleton bar paints and labels itself accordingly."""
    now = time.time()
    infos = [
        _info("tests/test_b.py", None, PyTestFlyExitCode.NONE, now - 10),
        _info("tests/test_b.py", 1, PyTestFlyExitCode.NONE, now - 9),
        _info("tests/test_b.py", 1, PyTestFlyExitCode.OK, now - 5, output="1 passed"),
    ]
    bar = PytestProgressBar(infos, now - 10, now, PytestRunState(infos), is_singleton=True)
    bar.resize(400, 20)
    bar.grab()


def test_progress_bar_empty_paints_nothing(app):
    """An empty status list paints via the base class and keeps no bar rect."""
    now = time.time()
    bar = PytestProgressBar([], now - 10, now, PytestRunState([]))
    bar.resize(400, 20)
    bar.grab()
    assert bar._last_bar_rect is None


def test_progress_bar_mouse_move_shows_and_hides_tooltip(app):
    """Moving over the drawn bar shows a tooltip; moving outside hides it."""
    now = time.time()
    infos = [
        _info("tests/test_c.py", None, PyTestFlyExitCode.NONE, now - 10),
        _info("tests/test_c.py", 1, PyTestFlyExitCode.NONE, now - 9),
        _info("tests/test_c.py", 1, PyTestFlyExitCode.OK, now - 5, output="captured output line"),
    ]
    bar = PytestProgressBar(infos, now - 10, now, PytestRunState(infos))
    bar.resize(400, 20)
    bar.grab()
    assert bar._last_bar_rect is not None

    center = bar._last_bar_rect.center()
    over = QMouseEvent(QEvent.Type.MouseMove, QPointF(center), QPointF(center), Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    bar.mouseMoveEvent(over)  # inside the bar -> showText branch

    outside = QPointF(bar._last_bar_rect.right() + 50, bar._last_bar_rect.bottom() + 50)
    away = QMouseEvent(QEvent.Type.MouseMove, outside, outside, Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    bar.mouseMoveEvent(away)  # outside -> hideText branch


def test_progress_bar_leave_event(app):
    """leaveEvent hides any visible tooltip without error."""
    now = time.time()
    infos = [_info("tests/test_d.py", 1, PyTestFlyExitCode.OK, now, output="x")]
    bar = PytestProgressBar(infos, now - 10, now, PytestRunState(infos))
    bar.leaveEvent(QEvent(QEvent.Type.Leave))
