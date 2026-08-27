"""
System commit-charge reader.

On Windows the memory limit that actually breaks parallel test runs is the *system
commit limit* (physical RAM + pagefile), not free physical RAM — the failure surfaces
as "the paging file is too small for this operation to complete" and as crashed workers.
Neither ``psutil.virtual_memory()`` (physical RAM) nor ``psutil.swap_memory()`` (pagefile
*in use*) exposes the commit limit, so a ``ctypes`` call to ``GetPerformanceInfo`` is
required.

The OS-specific read is isolated behind :func:`commit_charge_and_limit` so other
platforms can be added later without touching callers.  Every read is fail-open: any
error (or running on an unsupported platform) returns ``None`` instead of raising, so a
bad memory reading never breaks the GUI or a test run.
"""

import sys
from collections import defaultdict
from dataclasses import dataclass

import psutil

from ..logger import get_logger

log = get_logger()

# Log a failed/unsupported read only once — the system monitor calls this ~1 Hz and we
# do not want to spam the log.
_warned_once = False
# Same one-shot guard for the pagefile-config read.
_pagefile_warned_once = False


@dataclass(frozen=True)
class PageFileInfo:
    """One configured Windows paging file (a component of the system commit limit).

    Sizes are the *configured* values from the registry (what the Windows "Virtual Memory"
    dialog shows).  ``system_managed`` entries have ``initial_mb == maximum_mb == 0`` — Windows
    sizes them automatically, so the configured numbers are zero and the live size is only
    knowable from the commit limit (RAM + actual pagefile).
    """

    path: str  # full path, e.g. r"C:\pagefile.sys"
    drive: str  # drive the pagefile lives on, e.g. "C:"
    initial_mb: int  # configured initial size in MB (0 when system-managed)
    maximum_mb: int  # configured maximum size in MB (0 when system-managed)
    system_managed: bool  # True when Windows manages the size automatically


def commit_charge_and_limit() -> tuple[int, int] | None:
    """Return ``(commit_total, commit_limit)`` in **bytes**, or ``None`` if unavailable.

    ``commit_total`` is the current system commit charge; ``commit_limit`` is the maximum
    (physical RAM + current pagefile size).  Returns ``None`` on non-Windows platforms and
    on any error — callers must treat ``None`` as "signal unavailable" and degrade safely.
    """
    global _warned_once

    # Single return point per platform keeps the seam obvious for future platforms.
    # Future Linux support: parse ``/proc/meminfo`` ``CommitLimit`` and ``Committed_AS``.
    if sys.platform != "win32":
        return None

    try:
        import ctypes
        from ctypes import wintypes

        class PerformanceInformation(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("CommitTotal", ctypes.c_size_t),
                ("CommitLimit", ctypes.c_size_t),
                ("CommitPeak", ctypes.c_size_t),
                ("PhysicalTotal", ctypes.c_size_t),
                ("PhysicalAvailable", ctypes.c_size_t),
                ("SystemCache", ctypes.c_size_t),
                ("KernelTotal", ctypes.c_size_t),
                ("KernelPaged", ctypes.c_size_t),
                ("KernelNonpaged", ctypes.c_size_t),
                ("PageSize", ctypes.c_size_t),
                ("HandleCount", wintypes.DWORD),
                ("ProcessCount", wintypes.DWORD),
                ("ThreadCount", wintypes.DWORD),
            ]

        info = PerformanceInformation()
        info.cb = ctypes.sizeof(info)
        # CommitTotal/CommitLimit are in pages; multiply by PageSize for bytes.
        if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):
            raise OSError("GetPerformanceInfo failed")
        page = info.PageSize
        return info.CommitTotal * page, info.CommitLimit * page
    except (OSError, AttributeError, ValueError) as e:  # ctypes/psapi load or call failure
        if not _warned_once:
            log.warning(f"could not read system commit charge ({e}); commit indicator disabled")
            _warned_once = True
        return None


def pagefile_breakdown() -> list[PageFileInfo]:
    """Return the configured Windows paging files (the discs + sizes that, with physical RAM,
    make up the system commit limit).

    Read from ``HKLM\\SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Memory Management``'s
    ``PagingFiles`` value — the same source the Windows "Virtual Memory" dialog uses, so it needs
    no extra dependency and never blocks (a plain registry read).  Returns ``[]`` on non-Windows
    platforms and on any error (fail-open) so a bad read never breaks the GUI.
    """
    global _pagefile_warned_once

    if sys.platform != "win32":
        return []

    try:
        import os
        import winreg

        system_drive = os.environ.get("SystemDrive", "C:")
        key_path = r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            raw, _value_type = winreg.QueryValueEx(key, "PagingFiles")

        # PagingFiles is a REG_MULTI_SZ (list of strings); each line is "<path> <initial> <max>".
        lines = list(raw) if isinstance(raw, (list, tuple)) else str(raw).splitlines()
        entries: list[PageFileInfo] = []
        for line in lines:
            line = (line or "").strip()
            if not line:
                continue
            parts = line.split()
            path = parts[0]
            # System-managed pagefiles on the system drive are recorded as "?:\pagefile.sys".
            drive = os.path.splitdrive(path)[0] or path[:2]
            if drive.startswith("?"):
                drive = system_drive
            try:
                initial_mb = int(parts[1]) if len(parts) > 1 else 0
                maximum_mb = int(parts[2]) if len(parts) > 2 else 0
            except ValueError:
                initial_mb = maximum_mb = 0
            system_managed = initial_mb == 0 and maximum_mb == 0
            entries.append(PageFileInfo(path=path, drive=drive.upper(), initial_mb=initial_mb, maximum_mb=maximum_mb, system_managed=system_managed))
        return entries
    except (OSError, ValueError) as e:  # registry read failure or malformed PagingFiles value
        if not _pagefile_warned_once:
            log.warning(f"could not read pagefile configuration ({e}); pagefile breakdown disabled")
            _pagefile_warned_once = True
        return []


# Exception types every psutil tree read can raise; treated as "tree unreadable" and
# failed open by the helpers below.  ValueError: psutil rejects non-positive PIDs.
PSUTIL_READ_ERRORS = (psutil.NoSuchProcess, psutil.AccessDenied, ValueError)


def subtree_processes(pid: int) -> list[psutil.Process]:
    """Return *pid*'s process plus all its descendants; empty when the tree can't be read (fail-open).

    Constructs a fresh ``psutil.Process`` per tree member on every call (``children()``'s
    behavior), so this is for one-shot reads (e.g. the tree-kill path).  Repeated sampling
    must use :func:`subtree_pids` / :class:`ProcessHandleCache` instead — each construction
    runs a native init (a ``create_time`` identity read), and a native access-violation
    crash during garbage collection (Windows, Python 3.14) has been observed with exactly
    those construction frames on the stack, so high-frequency callers keep constructions
    to first-sight-per-pid.
    """
    try:
        proc = psutil.Process(pid)
        return [proc, *proc.children(recursive=True)]
    except PSUTIL_READ_ERRORS:
        return []


def _ppid_snapshot() -> dict[int, int] | None:
    """Return a one-shot ``{pid: ppid}`` map of every running process, or ``None`` when unavailable.

    Reads psutil's internal map (``psutil._ppid_map`` — the same snapshot ``Process.children()``
    is built on) which constructs no ``psutil.Process`` handles at all.  Private psutil API, so
    fail-open: when it's missing or errors, return ``None`` and let callers fall back to the
    handle-constructing ``children()`` walk.
    """
    ppid_map = getattr(psutil, "_ppid_map", None)
    if ppid_map is None:
        return None
    try:
        return ppid_map()
    except (psutil.Error, OSError):
        return None


def subtree_pids(pid: int) -> list[int]:
    """Return *pid* plus all descendant pids without constructing any ``psutil.Process`` handles.

    Same tree :func:`subtree_processes` walks, but membership only, computed from one
    ``{pid: ppid}`` snapshot.  Empty when the process doesn't exist (fail-open, matching
    ``subtree_processes``).  The root pid is always first in the returned list.
    """
    snapshot = _ppid_snapshot()
    if snapshot is None:
        return [p.pid for p in subtree_processes(pid)]
    if pid not in snapshot:
        return []
    children_of: defaultdict[int, list[int]] = defaultdict(list)
    for child_pid, parent_pid in snapshot.items():
        children_of[parent_pid].append(child_pid)
    # DFS over the snapshot; ``seen`` guards against cycles from pid reuse racing the
    # snapshot (the same guard psutil's children(recursive=True) uses).
    members = [pid]
    seen = {pid}
    stack = [pid]
    while stack:
        current_pid = stack.pop()
        for child_pid in children_of.get(current_pid, ()):
            if child_pid not in seen:
                seen.add(child_pid)
                members.append(child_pid)
                stack.append(child_pid)
    return members


class ProcessHandleCache:
    """Persistent ``pid → psutil.Process`` handles for repeated reads of the same subtree.

    Constructing a ``psutil.Process`` runs a native init (a ``create_time`` identity read);
    a caller that re-reads the same tree every sample would otherwise re-run that native
    init for every member on every sample (see :func:`subtree_processes`).  Keep one cache
    per sampled root and handles are constructed only at first sight of a pid.

    Handles self-heal on pid reuse: psutil's identity check makes any method call on a
    stale handle raise ``NoSuchProcess``, at which point callers :meth:`drop` it and the
    next :meth:`get` constructs a fresh one.
    """

    def __init__(self) -> None:
        self._procs: dict[int, psutil.Process] = {}

    def get(self, pid: int) -> psutil.Process | None:
        """Return the cached handle for *pid*, constructing it at first sight; ``None`` when unreadable."""
        handle = self._procs.get(pid)
        if handle is None:
            try:
                handle = psutil.Process(pid)
            except PSUTIL_READ_ERRORS:
                return None
            self._procs[pid] = handle
        return handle

    def drop(self, pid: int) -> None:
        """Forget *pid*'s handle (its process exited or its pid was reused)."""
        self._procs.pop(pid, None)

    def prune_to(self, live_pids: set[int]) -> None:
        """Drop every cached handle whose pid is not in *live_pids*, keeping the cache bounded."""
        for cached_pid in list(self._procs):
            if cached_pid not in live_pids:
                del self._procs[cached_pid]


def subtree_commit(pid: int, handle_cache: ProcessHandleCache | None = None) -> int:
    """Return the commit charge of *pid* plus all its descendants, in **bytes**.

    A test module may spawn its own subprocess tree, so the module's true memory cost is
    the sum over the worker process and every descendant.  On Windows this uses each
    process's ``pagefile`` (the "Commit Size" shown in Task Manager); on other platforms
    it falls back to ``vms`` as an approximation.  Fails open — returns ``0`` if the tree
    can't be read (the process already exited, access denied, etc.).

    Callers sampling repeatedly (e.g. once per monitor tick) must pass a persistent
    *handle_cache* dedicated to this root: handles are then constructed only for
    newly-seen pids instead of the whole subtree every call (fewer native ``Process``
    inits — see :class:`ProcessHandleCache`).
    """
    total = 0
    member_pids = subtree_pids(pid)
    for member_pid in member_pids:
        if handle_cache is None:
            try:
                member = psutil.Process(member_pid)
            except PSUTIL_READ_ERRORS:
                continue
        else:
            member = handle_cache.get(member_pid)
            if member is None:
                continue
        try:
            mem = member.memory_info()
            total += getattr(mem, "pagefile", None) or mem.vms
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            if handle_cache is not None:
                handle_cache.drop(member_pid)
    if handle_cache is not None:
        handle_cache.prune_to(set(member_pids))
    return total


def subtree_process_count(pid: int) -> int:
    """Return the number of processes in *pid*'s tree (the process itself plus all descendants).

    Counts grandchildren the controller never spawned directly — the spawn-explosion signal
    the commit-charge gate misses.  Fails open — returns ``0`` (i.e. "below any ceiling", so
    admit) if the tree can't be read.  Membership-only (:func:`subtree_pids`), so counting
    constructs no ``psutil.Process`` handles.
    """
    return len(subtree_pids(pid))


def commit_warning_active(commit_percent: float, commit_total_gb: float, threshold_fraction: float) -> bool:
    """Return ``True`` when commit charge is over the warning threshold.

    :param commit_percent: Commit charge as a percent of the commit limit (0-100).
    :param commit_total_gb: The commit limit in GiB.  ``<= 0`` means the signal is
        unavailable (fail-open), in which case the warning never fires.
    :param threshold_fraction: Warning threshold as a fraction of the limit (0.0-1.0).
    """
    if commit_total_gb <= 0:
        return False
    return commit_percent / 100.0 > threshold_fraction
