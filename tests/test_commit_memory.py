"""Tests for pytest_runner.commit_memory."""

import os
import sys

import pytest

from pytest_fly.pytest_runner import commit_memory
from pytest_fly.pytest_runner.commit_memory import PageFileInfo, commit_charge_and_limit, commit_warning_active, pagefile_breakdown, subtree_commit


@pytest.mark.skipif(sys.platform != "win32", reason="commit charge read is Windows-only in v1")
def test_commit_charge_and_limit_windows():
    result = commit_charge_and_limit()
    assert result is not None, "expected a (total, limit) tuple on Windows"
    total, limit = result
    assert isinstance(total, int) and isinstance(limit, int)
    assert limit > 0
    assert 0 <= total <= limit


def test_commit_charge_and_limit_non_windows(monkeypatch):
    """On non-Windows platforms the read returns None rather than raising."""
    monkeypatch.setattr(commit_memory.sys, "platform", "linux")
    assert commit_charge_and_limit() is None


def test_commit_charge_and_limit_fails_open(monkeypatch):
    """Any error during the read degrades to None (fail-open), never an exception."""
    # Force the win32 branch, then make the ctypes import inside it explode.
    monkeypatch.setattr(commit_memory.sys, "platform", "win32")
    monkeypatch.setattr(commit_memory, "_warned_once", False)

    real_import = __import__

    def boom(name, *args, **kwargs):
        if name == "ctypes":
            raise OSError("simulated failure")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", boom)
    assert commit_charge_and_limit() is None  # no exception propagates


def test_subtree_commit_current_process():
    # The current process is alive, so its subtree commit must be positive.
    assert subtree_commit(os.getpid()) > 0


def test_subtree_commit_missing_pid_fails_open():
    # A PID that cannot exist degrades to 0 rather than raising.
    assert subtree_commit(-1) == 0


def test_pagefile_breakdown_windows():
    """On Windows the read returns a list of PageFileInfo (typically at least one pagefile)."""
    result = pagefile_breakdown()
    assert isinstance(result, list)
    for pf in result:
        assert isinstance(pf, PageFileInfo)
        assert pf.drive  # a drive was parsed
        assert pf.initial_mb >= 0 and pf.maximum_mb >= 0
        # system_managed entries have both configured sizes at zero.
        assert pf.system_managed == (pf.initial_mb == 0 and pf.maximum_mb == 0)


def test_pagefile_breakdown_non_windows(monkeypatch):
    """On non-Windows platforms the read returns [] rather than raising."""
    monkeypatch.setattr(commit_memory.sys, "platform", "linux")
    assert pagefile_breakdown() == []


def test_pagefile_breakdown_fails_open(monkeypatch):
    """Any error during the read degrades to [] (fail-open), never an exception."""
    monkeypatch.setattr(commit_memory.sys, "platform", "win32")
    monkeypatch.setattr(commit_memory, "_pagefile_warned_once", False)

    real_import = __import__

    def boom(name, *args, **kwargs):
        if name == "winreg":
            raise OSError("simulated failure")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", boom)
    assert pagefile_breakdown() == []  # no exception propagates


def test_commit_warning_active():
    # Over threshold -> warn.
    assert commit_warning_active(commit_percent=90.0, commit_total_gb=32.0, threshold_fraction=0.85) is True
    # Below threshold -> no warn.
    assert commit_warning_active(commit_percent=50.0, commit_total_gb=32.0, threshold_fraction=0.85) is False
    # Exactly at threshold -> not strictly over -> no warn.
    assert commit_warning_active(commit_percent=85.0, commit_total_gb=32.0, threshold_fraction=0.85) is False
    # Unavailable signal (commit_total_gb == 0) -> never warn, even at 100%.
    assert commit_warning_active(commit_percent=100.0, commit_total_gb=0.0, threshold_fraction=0.85) is False
