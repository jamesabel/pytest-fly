"""Tests for pytest_runner.commit_memory."""

import ctypes
import os
import re
import sys

import pytest

from pytest_fly.pytest_runner import commit_memory
from pytest_fly.pytest_runner.commit_memory import (
    PageFileInfo,
    PageFileUsage,
    active_pagefiles,
    commit_charge_and_limit,
    commit_warning_active,
    pagefile_breakdown,
    parse_pagefile_information,
    subtree_commit,
)


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


# --- active_pagefiles (the kernel's live page-file list) -------------------------------------

_PAGE = 4096  # page size the parser tests convert with (any value works; the kernel's is mmap.PAGESIZE)

C_FILE = PageFileUsage(path="C:\\pagefile.sys", total_bytes=26 * 1024**3, in_use_bytes=512 * 1024**2, peak_bytes=25 * 1024**3)
V_FILE = PageFileUsage(path="V:\\pagefile.sys", total_bytes=128 * 1024**3, in_use_bytes=128 * 1024**2, peak_bytes=256 * 1024**2)


# AI-authored helper (Claude Code) for the AI-generated parser tests below.
def _pagefile_information_buffer(files: list[PageFileUsage]):
    """Build a ``SystemPageFileInformation`` buffer as the kernel lays it out: the entries chained by
    ``NextEntryOffset``, each name (NT path, UTF-16) placed after the entry table with ``Buffer``
    pointing at it."""
    entry_size = ctypes.sizeof(commit_memory._PageFileInformation)
    names = [f"\\??\\{f.path}".encode("utf-16-le") for f in files]
    buffer = ctypes.create_string_buffer(entry_size * len(files) + sum(map(len, names)) + 2)
    name_offset = entry_size * len(files)
    for index, (f, name) in enumerate(zip(files, names, strict=True)):
        entry = commit_memory._PageFileInformation.from_buffer(buffer, index * entry_size)
        entry.NextEntryOffset = entry_size if index < len(files) - 1 else 0
        entry.TotalSize = f.total_bytes // _PAGE
        entry.TotalInUse = f.in_use_bytes // _PAGE
        entry.PeakUsage = f.peak_bytes // _PAGE
        entry.PageFileName.Length = len(name)
        entry.PageFileName.MaximumLength = len(name) + 2
        entry.PageFileName.Buffer = ctypes.addressof(buffer) + name_offset
        buffer[name_offset : name_offset + len(name)] = name
        name_offset += len(name)
    return buffer


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
def test_parse_pagefile_information_walks_the_chain():
    """A two-entry buffer parses to both files in order, the NT prefix stripped and pages converted to bytes."""
    buffer = _pagefile_information_buffer([C_FILE, V_FILE])
    assert parse_pagefile_information(buffer, _PAGE) == [C_FILE, V_FILE]


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
def test_parse_pagefile_information_single_entry():
    """A one-entry buffer (NextEntryOffset 0 on the first entry) parses to just that file."""
    assert parse_pagefile_information(_pagefile_information_buffer([V_FILE]), _PAGE) == [V_FILE]


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
def test_pagefile_usage_percent():
    assert C_FILE.percent == pytest.approx(100.0 * 512 / (26 * 1024))
    assert PageFileUsage(path="X:\\pagefile.sys", total_bytes=0, in_use_bytes=0, peak_bytes=0).percent == 0.0  # no division by zero


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
def test_active_pagefiles_non_windows(monkeypatch):
    """On non-Windows platforms the read returns [] without touching the kernel and without a warning."""
    warnings: list[str] = []
    monkeypatch.setattr(commit_memory.log, "warning", lambda message: warnings.append(message))
    monkeypatch.setattr(commit_memory, "_active_pagefiles_warned_once", False)
    monkeypatch.setattr(commit_memory.sys, "platform", "linux")
    assert active_pagefiles() == []
    assert warnings == []


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
@pytest.mark.skipif(sys.platform != "win32", reason="exercises the real NtQuerySystemInformation call")
def test_active_pagefiles_fails_open(monkeypatch):
    """A failed kernel read (an invalid information class) degrades to [] and logs exactly one warning."""
    warnings: list[str] = []
    monkeypatch.setattr(commit_memory.log, "warning", lambda message: warnings.append(message))
    monkeypatch.setattr(commit_memory, "_active_pagefiles_warned_once", False)
    monkeypatch.setattr(commit_memory, "_SYSTEM_PAGEFILE_INFORMATION", 0xFFFF)  # STATUS_INVALID_INFO_CLASS
    assert active_pagefiles() == []
    assert active_pagefiles() == []
    assert len(warnings) == 1


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
@pytest.mark.skipif(sys.platform != "win32", reason="the active page files are read on Windows only")
def test_active_pagefiles_windows():
    """On Windows the kernel lists at least one page file, each a <drive>:\\...pagefile.sys with sane use."""
    files = active_pagefiles()
    assert files, "Windows always has at least one page file"
    for pf in files:
        assert isinstance(pf, PageFileUsage)
        assert re.fullmatch(r"[A-Za-z]:\\.*pagefile\.sys", pf.path, re.IGNORECASE), pf.path
        assert 0 < pf.total_bytes
        assert 0 <= pf.in_use_bytes <= pf.total_bytes
        assert 0.0 <= pf.percent <= 100.0
