"""
Cross-platform file-system helpers with retry logic.

Functions in this module retry transient failures (locked files, pending
deletes on Windows, etc.) with configurable back-off so callers don't have
to manage this themselves.
"""

import os
import shutil
import stat
import sys
import time
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Union

from typeguard import typechecked

from ..logger import get_logger

log = get_logger()


class RemoveDirectoryException(Exception):
    """Raised when a directory cannot be removed after exhausting retries."""


@cache
def is_windows() -> bool:
    """Return ``True`` when running on Windows."""
    return sys.platform.lower().startswith("win")


@cache
def is_linux() -> bool:
    """Return ``True`` when running on Linux."""
    return sys.platform.lower().startswith("linux")


@typechecked()
def remove_readonly(path: Union[Path, str]):
    """Remove the read-only flag from *path* so it can be deleted."""
    os.chmod(path, stat.S_IWRITE)


def remove_readonly_onerror(func, path, excinfo):
    """``onerror`` callback for :func:`shutil.rmtree` — strips read-only and retries."""
    remove_readonly(path)
    func(path)


def _retry_operation(
    operation: Callable[[], None],
    exists_check: Callable[[], bool],
    attempt_limit: int,
    initial_delay: float,
    exponential_backoff: bool = False,
) -> tuple[bool, int, Exception | None]:
    """Retry *operation* until *exists_check* returns ``False`` or attempts are exhausted.

    :param operation: Callable that performs the removal (may raise ``FileNotFoundError``,
                      ``PermissionError``, or ``OSError``).
    :param exists_check: Callable returning ``True`` while the target still exists.
    :param attempt_limit: Maximum number of attempts.
    :param initial_delay: Seconds to wait between attempts.
    :param exponential_backoff: If ``True``, double the delay after each attempt.
    :return: ``(success, attempt_count, last_exception)``.
    """
    attempt_count = 0
    delay = initial_delay
    reason: Exception | None = None
    while exists_check() and attempt_count < attempt_limit:
        attempt_count += 1
        try:
            operation()
        except FileNotFoundError as e:
            reason = e
            log.debug(f"retry {attempt_count}: {e}")
        except (PermissionError, OSError) as e:
            reason = e
            log.info(f"retry {attempt_count}: {e}")
        if exists_check():
            time.sleep(delay)
        if exponential_backoff:
            delay *= 2.0
    success = not exists_check()
    return success, attempt_count, reason


@typechecked()
def rm_file(p: Union[Path, str], log_function=log.error) -> bool:
    """Remove a single file, retrying with exponential back-off on transient errors.

    :param p: Path to the file to remove.
    :param log_function: Logging function called on final failure.
    :return: ``True`` if the file no longer exists.
    """
    if isinstance(p, str):
        p = Path(p)

    def _do_remove():
        remove_readonly(p)
        p.unlink(True)

    success, attempt_count, reason = _retry_operation(
        operation=_do_remove,
        exists_check=p.exists,
        attempt_limit=5,
        initial_delay=1.0,
        exponential_backoff=True,
    )
    if not success:
        log_function(f"could not remove {p} ({attempt_count=}, {reason=})", stack_info=True)
    return success


def is_file_locked(file_path: Path) -> bool:
    """Return ``True`` if *file_path* is currently locked by another process."""
    if not file_path.exists():
        return False

    try:
        with file_path.open("a"):
            pass
        return False
    except (IOError, PermissionError):
        return True


def set_read_only(path: Path):
    """Make *path* read-only (platform-aware permissions)."""
    if is_windows():
        os.chmod(path, stat.S_IREAD)
    else:
        os.chmod(path, 0o444)


def set_read_write(path: Path):
    """Make *path* readable and writable (platform-aware permissions)."""
    if is_windows():
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    else:
        os.chmod(path, 0o666)


def is_read_only(path: Path) -> bool:
    """Return ``True`` if *path* is read-only."""
    if is_windows():
        return not os.access(path, os.W_OK)
    else:
        return not (path.stat().st_mode & stat.S_IWUSR)


def is_read_write(path: Path) -> bool:
    """Return ``True`` if *path* is both readable and writable."""
    if is_windows():
        return os.access(path, os.R_OK) and os.access(path, os.W_OK)
    else:
        path_stat = path.stat()
        return bool(path_stat.st_mode & stat.S_IWRITE and path_stat.st_mode & stat.S_IREAD)


@typechecked()
def rm_dir(p: Union[Path, str], log_function=log.warning, attempt_limit: int = 20, delay: float = 0.1) -> bool:
    """Remove a directory tree, retrying on transient errors.

    :param p: Directory to remove.
    :param log_function: Logging function called on final failure.
    :param attempt_limit: Maximum removal attempts.
    :param delay: Seconds between retries (fixed, no exponential back-off).
    :return: ``True`` if the directory no longer exists.
    :raises RemoveDirectoryException: If removal fails after all attempts.
    """
    start = time.time()
    if isinstance(p, str):
        p = Path(p)

    success, attempt_count, reason = _retry_operation(
        operation=lambda: shutil.rmtree(p, onerror=remove_readonly_onerror),
        exists_check=p.exists,
        attempt_limit=attempt_limit,
        initial_delay=delay,
    )
    duration = time.time() - start
    log.info(f'"{p}",{success=},{attempt_count=},{duration=},{reason=},{attempt_limit=},{delay=}')
    if not success:
        log_function(f'could not remove "{p}",{success=},{attempt_count=},{duration=},{reason=},{attempt_limit=},{delay=}')
        raise RemoveDirectoryException(f'Could not remove "{p}"')
    return success


def mk_dirs(d, remove_first=False, log_function=log.error):
    """Create a directory tree, optionally removing it first.

    Retries ``os.makedirs`` in a loop because, on Windows, the directory may
    not be visible immediately after creation.

    :param d: Directory path to create.
    :param remove_first: If ``True``, remove the directory before creating it.
    :param log_function: Logging function called on final failure.
    """
    if remove_first:
        rm_dir(d, log_function)
    # sometimes when os.makedirs exits the dir is not actually there
    count = 600
    while count > 0 and not os.path.exists(d):
        try:
            # for some reason we can get the FileNotFoundError exception
            os.makedirs(d, exist_ok=True)
        except FileNotFoundError:
            pass
        if not os.path.exists(d):
            time.sleep(0.1)
        count -= 1
    if not os.path.exists(d):
        log_function(f'could not mkdirs "{d}" ({os.path.abspath(d)})')
