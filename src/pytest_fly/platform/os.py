import os
import stat
import time
from pathlib import Path
from typing import Union
from logging import getLogger
import sys
from functools import cache
import shutil

from typeguard import typechecked

log = getLogger(__file__)


class RemoveDirectoryException(Exception):
    pass


@cache
def is_windows():
    return sys.platform.lower().startswith("win")


@cache
def is_linux():
    return sys.platform.lower().startswith("linux")


@typechecked()
def remove_readonly(path: Union[Path, str]):
    os.chmod(path, stat.S_IWRITE)


# sometimes needed for Windows
def remove_readonly_onerror(func, path, excinfo):
    remove_readonly(path)
    func(path)


@typechecked()
def rm_file(p: Union[Path, str], log_function=log.error) -> bool:
    if isinstance(p, str):
        p = Path(p)

    retry_count = 0
    retry_limit = 5
    delete_ok = False
    delay = 1.0
    reason = None  # type: FileNotFoundError | PermissionError | OSError | None
    while p.exists() and retry_count < retry_limit:
        try:
            remove_readonly(p)
            p.unlink(True)
            delete_ok = True
        except FileNotFoundError as e:
            reason = e
            log.debug(f"{p} ({retry_count=}, {reason=})")  # this can happen when first doing the shutil.rmtree()
            time.sleep(delay)
        except (PermissionError, OSError) as e:
            reason = e
            log.info(f"{p} ({retry_count=}, {reason=})")
            time.sleep(delay)
        time.sleep(0.1)
        if p.exists():
            time.sleep(delay)
        retry_count += 1
        delay *= 2.0
    if p.exists():
        log_function(f"could not remove {p} ({retry_count=}, {reason=})", stack_info=True)
    else:
        delete_ok = True
    return delete_ok


def is_file_locked(file_path: Path) -> bool:
    """Check if a file is locked."""
    if not file_path.exists():
        return False  # File does not exist, so it's not locked

    try:
        with file_path.open("a"):
            pass
        return False
    except (IOError, PermissionError):
        return True


def set_read_only(path: Path):
    if is_windows():
        os.chmod(path, stat.S_IREAD)
    else:
        # Unix-like systems
        os.chmod(path, 0o444)


def set_read_write(path: Path):
    if is_windows():
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    else:
        # Unix-like systems
        os.chmod(path, 0o666)


def is_read_only(path: Path) -> bool:
    if is_windows():  # Windows
        return not os.access(path, os.W_OK)
    else:
        # Unix-like systems
        return not (path.stat().st_mode & stat.S_IWUSR)


def is_read_write(path: Path) -> bool:
    if is_windows():  # Windows
        return os.access(path, os.R_OK) and os.access(path, os.W_OK)
    else:  # Unix-like systems
        path_stat = path.stat()
        return bool(path_stat.st_mode & stat.S_IWRITE and path_stat.st_mode & stat.S_IREAD)


@typechecked()
def rm_dir(p: Union[Path, str], log_function=log.warning, attempt_limit: int = 20, delay: float = 0.1) -> bool:
    """
    Remove a directory and all its contents. Retry if there are errors.

    :param p: the directory to remove
    :param log_function: the function to log messages
    :param attempt_limit: the number of times to attempt to remove the directory
    :param delay: the delay between retries
    """

    start = time.time()
    if isinstance(p, str):
        p = Path(p)
    attempt_count = 0
    reason = None  # type: FileNotFoundError | PermissionError | OSError | None
    while p.exists() and attempt_count < attempt_limit:
        attempt_count += 1
        try:
            shutil.rmtree(p, onerror=remove_readonly_onerror)
        except FileNotFoundError as e:
            reason = e  # assign error to a variable so we can use it later in this function
            log.debug(f"{p} ({attempt_count=}, {reason=})")  # this can happen when first doing the shutil.rmtree()
        except (PermissionError, OSError) as e:
            reason = e  # assign error to a variable so we can use it later in this function
            log.info(f"{p} ({attempt_count=}, {reason=})")
        if p.exists():
            time.sleep(delay)
    if p.exists():
        duration = time.time() - start
        delete_ok = False
        log_function(f'could not remove "{p}",{delete_ok=},{attempt_count=},{duration=},{reason=},{attempt_limit=},{delay=}')
    else:
        delete_ok = True
    duration = time.time() - start
    log.info(f'"{p}",{delete_ok=},{attempt_count=},{duration=},{reason=},{attempt_limit=},{delay=}')
    if not delete_ok:
        raise RemoveDirectoryException(f'Could not remove "{p}"')
    return delete_ok


def mk_dirs(d, remove_first=False, log_function=log.error):
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
