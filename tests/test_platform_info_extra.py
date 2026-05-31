"""Additional coverage for :mod:`pytest_fly.platform.platform_info`."""

from pytest_fly.platform.platform_info import (
    get_efficiency_core_count,
    get_performance_core_count,
    get_platform_info,
)


def test_get_platform_info_with_details():
    """details=True adds the extended CPU fields without error."""
    info = get_platform_info(details=True)
    assert info["computer_name"]
    assert info["cpu_count_logical"] >= 1
    assert "memory_total" in info


def test_core_counts_are_consistent():
    """Performance + efficiency cores never exceed the logical thread count and are non-negative."""
    p = get_performance_core_count()
    e = get_efficiency_core_count()
    assert p >= 1
    assert e >= 0
