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

import psutil

from ..logger import get_logger

log = get_logger()

# Log a failed/unsupported read only once — the system monitor calls this ~1 Hz and we
# do not want to spam the log.
_warned_once = False


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
    except Exception as e:
        if not _warned_once:
            log.warning(f"could not read system commit charge ({e}); commit indicator disabled")
            _warned_once = True
        return None


def subtree_commit(pid: int) -> int:
    """Return the commit charge of *pid* plus all its descendants, in **bytes**.

    A test module may spawn its own subprocess tree, so the module's true memory cost is
    the sum over the worker process and every descendant.  On Windows this uses each
    process's ``pagefile`` (the "Commit Size" shown in Task Manager); on other platforms
    it falls back to ``vms`` as an approximation.  Fails open — returns ``0`` if the tree
    can't be read (the process already exited, access denied, etc.).
    """
    try:
        proc = psutil.Process(pid)
        procs = [proc, *proc.children(recursive=True)]
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
        # ValueError: psutil rejects non-positive PIDs.
        return 0
    total = 0
    for p in procs:
        try:
            mem = p.memory_info()
            total += getattr(mem, "pagefile", None) or mem.vms
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return total


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
