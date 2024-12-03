import os
import stat
import time
from pathlib import Path
from typing import Union
from logging import getLogger
import getpass
import platform
import sys
from functools import cache

from typeguard import typechecked

log = getLogger(__file__)


@cache
def get_user_name():
    return getpass.getuser()


@cache
def get_computer_name():
    return platform.node()


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
