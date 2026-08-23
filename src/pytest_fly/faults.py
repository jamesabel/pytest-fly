"""Fatal-error diagnostics.

``faulthandler`` writes the Python stack of every thread to a file descriptor when the process
dies from SIGSEGV / SIGABRT / SIGFPE / SIGBUS / SIGILL (on Windows, also an access violation).
It writes directly to the fd from the signal handler, so the output survives a crash that leaves
no traceback and no log record.

The dump file is opened once per process and the handle is held for the process lifetime —
closing it would leave ``faulthandler`` writing to a dead descriptor.  A clean exit leaves an
empty file; :func:`report_previous_crashes` sweeps those up on the next launch and surfaces any
non-empty one (a crash) in the log.
"""

import faulthandler
import os
from pathlib import Path

from tobool import to_bool

from .const import PYTEST_FLY_FAULTHANDLER_STRING
from .logger import EVENT_EXTRA, get_logger
from .paths import get_log_dir

log = get_logger()

_fault_file = None  # process-lifetime reference; never close it

_dump_prefix = "faulthandler-"
_crash_prefix = "faulthandler-crash-"
_dump_suffix = ".log"


def faulthandler_dump_path(pid: int | None = None) -> Path:
    """Path of a process's faulthandler dump file (this process when *pid* is ``None``)."""
    return Path(get_log_dir(), f"{_dump_prefix}{os.getpid() if pid is None else pid}{_dump_suffix}")


def faulthandler_enabled_by_env() -> bool:
    """Whether faulthandler is requested, per the inherited environment.

    The parent stamps ``PYTEST_FLY_FAULTHANDLER`` into ``os.environ`` at startup (see
    :func:`enable_faulthandler`), so spawn children need no preference lookup of their own.
    Unset means enabled — the handler must be armed before the crash nobody predicted.
    """
    value = os.environ.get(PYTEST_FLY_FAULTHANDLER_STRING)
    if value is None:
        return True
    parsed = to_bool(value)
    return True if parsed is None else parsed  # an unrecognized value keeps the safe default: armed


def enable_faulthandler(export_to_children: bool = False, requested: bool | None = None) -> Path | None:
    """Install the fatal-error handler for this process.

    :param export_to_children: parent only — stamp the resolved setting into ``os.environ`` so
                               spawned children inherit it without reading preferences.
    :param requested: explicit on/off; ``None`` means "read the environment".
    :return: the dump file path, or ``None`` if faulthandler is disabled or could not be enabled.
    """
    global _fault_file
    enabled = faulthandler_enabled_by_env() if requested is None else requested
    if export_to_children:
        os.environ[PYTEST_FLY_FAULTHANDLER_STRING] = "1" if enabled else "0"
    if not enabled:
        return None
    path = faulthandler_dump_path()
    try:
        # binary, append, unbuffered: faulthandler writes to the raw fd, and append means a
        # re-enable in the same process never truncates an earlier dump.
        _fault_file = open(path, "ab", buffering=0)
        faulthandler.enable(file=_fault_file, all_threads=True)
    except OSError as e:
        log.warning(f"could not enable faulthandler at {path}: {e}")
        return None
    return path


def report_previous_crashes(max_chars: int = 4000) -> list[Path]:
    """Log and archive any non-empty faulthandler dumps left by earlier sessions.

    A non-empty dump means some process died from a fatal signal.  Each is logged at WARNING (so
    it reaches the log file and the GUI Log tab) and renamed to ``faulthandler-crash-<pid>-<n>.log``
    so it is reported exactly once but never destroyed.  Empty dumps from prior runs (clean exits)
    are deleted.  A file still held by a live process (e.g. a second instance) is skipped.

    :param max_chars: cap on how much of each dump is echoed into the log.
    :return: the archived crash-dump paths.
    """
    archived: list[Path] = []
    log_dir = get_log_dir()
    own_path = faulthandler_dump_path()
    for path in sorted(log_dir.glob(f"{_dump_prefix}*{_dump_suffix}")):
        if path == own_path or path.name.startswith(_crash_prefix):
            continue
        try:
            if path.stat().st_size == 0:
                path.unlink()
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            pid = path.name[len(_dump_prefix) : -len(_dump_suffix)]
            archive = _next_archive_path(log_dir, pid)
            path.rename(archive)
        except OSError as e:
            log.info(f"skipping faulthandler dump {path}: {e}")  # locked by a live process, or already gone
            continue
        log.warning(f"previous session crashed ({archive.name}):\n{text[:max_chars]}", extra=EVENT_EXTRA)
        archived.append(archive)
    return archived


def _next_archive_path(log_dir: Path, pid: str) -> Path:
    """First unused ``faulthandler-crash-<pid>-<n>.log`` path (PIDs are reused, so number them)."""
    n = 1
    while (candidate := Path(log_dir, f"{_crash_prefix}{pid}-{n}{_dump_suffix}")).exists():
        n += 1
    return candidate
