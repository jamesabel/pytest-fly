import sys

import psutil

from pytest_fly.platform.platform_info import (
    _get_p_core_count_windows,
    get_efficiency_core_count,
    get_performance_core_count,
)


def test_p_core_count_windows_api():
    """On Windows the API-based helper must return a positive integer."""
    if sys.platform != "win32":
        return
    count = _get_p_core_count_windows()
    assert count is not None, "_get_p_core_count_windows() returned None on Windows"
    assert count > 0, f"Expected at least one P-core, got {count}"


def test_performance_core_count_positive():
    count = get_performance_core_count()
    assert count > 0, f"Expected at least one performance core, got {count}"


def test_performance_core_count_le_physical():
    """P-core count must not exceed the total physical core count."""
    p_cores = get_performance_core_count()
    physical = psutil.cpu_count(logical=False)
    assert p_cores <= physical, f"P-core count {p_cores} exceeds physical core count {physical}"


def test_efficiency_core_count_non_negative():
    assert get_efficiency_core_count() >= 0


def test_core_counts_sum_to_physical():
    """P-cores + E-cores must equal the total physical core count."""
    physical = psutil.cpu_count(logical=False)
    assert get_performance_core_count() + get_efficiency_core_count() == physical
