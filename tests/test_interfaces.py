"""Tests for ScheduledTest sorting and _lines_per_second."""

from pytest_fly.interfaces import ScheduledTest, _lines_per_second


def test_lines_per_second():
    assert _lines_per_second(10.0, 0.5) == 0.05
    assert _lines_per_second(1.0, 1.0) == 1.0
    # near-zero duration should not divide by zero
    result = _lines_per_second(0.0, 0.5)
    assert result > 0


def test_singleton_sorts_last():
    """Singletons should always sort after non-singletons."""
    normal = ScheduledTest("test_a", singleton=False, duration=None, coverage=None)
    single = ScheduledTest("test_b", singleton=True, duration=None, coverage=None)

    assert normal < single
    assert single > normal
    assert not (normal > single)
    assert not (single < normal)


def test_both_singletons_sort_by_node_id():
    """Two singletons with no duration data sort alphabetically by node_id."""
    a = ScheduledTest("aaa", singleton=True, duration=None, coverage=None)
    b = ScheduledTest("zzz", singleton=True, duration=None, coverage=None)

    assert a < b
    assert b > a


def test_none_duration_sorts_by_node_id():
    """When duration or coverage is None, fallback to node_id comparison."""
    a = ScheduledTest("test_a", singleton=False, duration=None, coverage=None)
    b = ScheduledTest("test_b", singleton=False, duration=None, coverage=None)

    assert a < b
    assert b > a


def test_coverage_efficiency_ordering():
    """Higher coverage efficiency (lines/sec) should sort earlier."""
    # fast_test: 0.8 coverage in 2s = 0.4 lines/sec
    fast = ScheduledTest("fast", singleton=False, duration=2.0, coverage=0.8)
    # slow_test: 0.8 coverage in 10s = 0.08 lines/sec
    slow = ScheduledTest("slow", singleton=False, duration=10.0, coverage=0.8)

    assert fast < slow  # fast should run earlier
    assert slow > fast


def test_sorted_list_order():
    """Sorting a list of ScheduledTests should produce the correct execution order."""
    tests = [
        ScheduledTest("singleton_z", singleton=True, duration=None, coverage=None),
        ScheduledTest("normal_b", singleton=False, duration=None, coverage=None),
        ScheduledTest("normal_a", singleton=False, duration=None, coverage=None),
        ScheduledTest("singleton_a", singleton=True, duration=None, coverage=None),
    ]
    result = sorted(tests)
    # Non-singletons first (alphabetical), then singletons (alphabetical)
    assert [t.node_id for t in result] == ["normal_a", "normal_b", "singleton_a", "singleton_z"]


def test_mixed_none_and_data():
    """A test with None duration should sort by node_id against another with None."""
    a = ScheduledTest("test_a", singleton=False, duration=5.0, coverage=None)
    b = ScheduledTest("test_b", singleton=False, duration=None, coverage=0.5)

    # Both have partial None, so fallback to node_id
    assert a < b
    assert b > a
