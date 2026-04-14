"""Tests for time_axis pure utility functions."""

from pytest_fly.gui.graph_tab.time_axis import _choose_interval, _format_tick_label, compute_grid_ticks


def test_choose_interval_short():
    """A 10-second window should use 1-second intervals."""
    assert _choose_interval(10.0) == 1


def test_choose_interval_medium():
    """A 60-second window should pick an interval that yields 5-12 lines."""
    interval = _choose_interval(60.0)
    num_lines = 60.0 / interval
    assert 5 <= num_lines <= 12


def test_choose_interval_long():
    """A 3600-second window should pick an interval that yields 5-12 lines."""
    interval = _choose_interval(3600.0)
    num_lines = 3600.0 / interval
    assert 5 <= num_lines <= 12


def test_choose_interval_very_long():
    """Beyond all candidates, should return the largest interval."""
    interval = _choose_interval(100000.0)
    assert interval == 600


def test_format_tick_label_seconds():
    assert _format_tick_label(0) == "0s"
    assert _format_tick_label(30) == "30s"
    assert _format_tick_label(59) == "59s"


def test_format_tick_label_minutes():
    assert _format_tick_label(60) == "1m"
    assert _format_tick_label(120) == "2m"
    assert _format_tick_label(300) == "5m"


def test_format_tick_label_mixed():
    assert _format_tick_label(90) == "1m30s"
    assert _format_tick_label(150) == "2m30s"


def test_compute_grid_ticks_none_timestamps():
    """Should return empty list when timestamps are None."""
    assert compute_grid_ticks(None, None, 800) == []
    assert compute_grid_ticks(100.0, None, 800) == []
    assert compute_grid_ticks(None, 200.0, 800) == []


def test_compute_grid_ticks_zero_width():
    assert compute_grid_ticks(100.0, 200.0, 0) == []
    assert compute_grid_ticks(100.0, 200.0, -1) == []


def test_compute_grid_ticks_valid():
    """Should return a list of (x_pixel, label) tuples."""
    ticks = compute_grid_ticks(1000.0, 1010.0, 800)
    assert len(ticks) > 0
    # First tick should be at x=0 with label "0s"
    assert ticks[0] == (0.0, "0s")
    # All x values should be non-negative
    assert all(x >= 0 for x, _ in ticks)


def test_compute_grid_ticks_same_timestamp():
    """When min == max, time_window is clamped to 1.0."""
    ticks = compute_grid_ticks(1000.0, 1000.0, 800)
    assert len(ticks) > 0
