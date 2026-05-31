"""Paint and interval-selection coverage for the Graph-tab time axis."""

import time

from pytest_fly.gui.graph_tab.time_axis import TimeAxisWidget, compute_grid_ticks


def test_compute_grid_ticks_huge_window_uses_largest_interval():
    """A window too large for any smaller interval falls back to the largest one."""
    ticks = compute_grid_ticks(0.0, 10_000_000.0, 800)
    assert len(ticks) > 0
    # With the 24h (86400s) interval the ticks are spaced far apart but still produced.
    assert ticks[0][1] == "0s"


def test_compute_grid_ticks_none_inputs():
    """Missing bounds or non-positive width yield no ticks."""
    assert compute_grid_ticks(None, 1.0, 800) == []
    assert compute_grid_ticks(0.0, 1.0, 0) == []


def test_time_axis_widget_paints(app):
    """A TimeAxisWidget with a valid window paints its tick marks and labels."""
    widget = TimeAxisWidget()
    widget.resize(400, 30)
    now = time.time()
    widget.update_time_window(now - 100, now)
    widget.grab()  # forces paintEvent with a populated tick set


def test_time_axis_widget_paints_empty(app):
    """With no time window the widget paints nothing (early return path)."""
    widget = TimeAxisWidget()
    widget.resize(400, 30)
    widget.grab()  # paintEvent with no ticks -> super().paintEvent
