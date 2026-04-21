"""Tests for interfaces (ScheduledTest identity and lines_per_second helper)."""

from pytest_fly.interfaces import ScheduledTest, lines_per_second


def test_lines_per_second_basic():
    assert lines_per_second(10.0, 0.5) == 0.05
    assert lines_per_second(1.0, 1.0) == 1.0


def test_lines_per_second_avoids_div_by_zero():
    result = lines_per_second(0.0, 0.5)
    assert result is not None
    assert result > 0


def test_lines_per_second_missing_inputs():
    assert lines_per_second(None, 0.5) is None
    assert lines_per_second(1.0, None) is None
    assert lines_per_second(None, None) is None


def test_scheduled_test_equality_by_node_id():
    a = ScheduledTest("test_a", singleton=False, duration=1.0, coverage=0.5)
    a_dup = ScheduledTest("test_a", singleton=True, duration=None, coverage=None)
    b = ScheduledTest("test_b", singleton=False, duration=1.0, coverage=0.5)
    assert a == a_dup  # node_id determines equality
    assert a != b
    assert hash(a) == hash(a_dup)
