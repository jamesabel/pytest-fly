"""Tests for :class:`pytest_fly.tick_data.TickData`."""

from pytest_fly.tick_data import TickData


def test_effective_min_time_stamp_prefers_run_start():
    """When current_run_start is set it wins over the earliest observed record."""
    tick = TickData(process_infos=[], min_time_stamp=100.0, current_run_start=150.0)
    assert tick.effective_min_time_stamp == 150.0


def test_effective_min_time_stamp_falls_back_to_min():
    """With no explicit run start, fall back to the earliest record timestamp."""
    tick = TickData(process_infos=[], min_time_stamp=100.0, current_run_start=None)
    assert tick.effective_min_time_stamp == 100.0


def test_effective_min_time_stamp_none_when_both_unset():
    """No run start and no records -> None."""
    tick = TickData(process_infos=[])
    assert tick.effective_min_time_stamp is None
