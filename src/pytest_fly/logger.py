"""Application logging — stdlib-only.

The parent GUI process calls :func:`init_parent_logger` once at startup.
Every :class:`multiprocessing.Process` subclass that logs from its ``run()``
method calls :func:`configure_child_logger` as the first line of that method:
spawn children inherit no handlers, and ``sys.stderr`` in a Windows spawn
child is not reliable (pytest's capture plumbing can leave it closed), so
each child writes its records directly to its own file in the shared log
directory.
"""

import logging
from logging import Formatter, Logger
from logging.handlers import RotatingFileHandler
from pathlib import Path

from platformdirs import user_log_dir

from pytest_fly.__version__ import application_name, author

_LOG_FORMAT = "%(asctime)s %(process)d %(name)s %(levelname)s %(message)s"
_MAX_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 5

_log_directory: Path | None = None


def _resolve_log_directory() -> Path:
    """Deterministic log directory, shared by parent and spawn children."""
    log_dir = Path(user_log_dir(application_name, author))
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _purge_process_monitor_logs(log_dir: Path) -> None:
    """Delete stale ``process_monitor-<pid>.log`` files left by prior runs.

    One of these is created per monitored PID (:meth:`ProcessMonitor.run`), but the
    monitor itself logs almost nothing, so they accumulate as thousands of orphaned
    near-empty files that slow every directory scan.  They are per-run ephemeral debug
    files, so a fresh parent launch can clear them.  Files still held open by a
    concurrently running instance raise on unlink and are skipped.
    """
    for path in log_dir.glob("process_monitor-*.log"):
        try:
            path.unlink()
        except OSError:
            pass  # locked by a live monitor, or already gone — leave it


def init_parent_logger(verbose: bool) -> Path:
    """Configure the parent process's root logger.

    GUI app: logs go to a rotating file only (10 MB, 5 backups). No stdout
    or stderr handler — a PySide6 app under ``pythonw``/frozen bundles has
    no attached console, and writing there can raise on closed streams.
    """
    global _log_directory
    log_dir = _resolve_log_directory()
    _purge_process_monitor_logs(log_dir)
    level = logging.DEBUG if verbose else logging.INFO
    formatter = Formatter(_LOG_FORMAT)

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(level)

    file_handler = RotatingFileHandler(log_dir / f"{application_name}.log", maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    _log_directory = log_dir
    return log_dir


def configure_child_logger(log_file_name: str) -> None:
    """Install a per-child :class:`RotatingFileHandler` on the root logger.

    Spawn children inherit no handlers; without this the stdlib falls back
    to ``logging.lastResort`` → a potentially-closed ``sys.stderr`` and
    raises ``ValueError`` on the first record. Each child writes DEBUG+ to
    its own file so nothing is dropped.

    The handler rotates (10 MB × 5 backups) so a chatty test no longer grows a
    single log without bound across runs — these files append on every run, and
    at DEBUG a single long test could otherwise reach gigabytes.
    """
    log_dir = _resolve_log_directory()
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(logging.DEBUG)
    file_handler = RotatingFileHandler(log_dir / log_file_name, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8")
    file_handler.setFormatter(Formatter(_LOG_FORMAT))
    root.addHandler(file_handler)


def get_log_directory() -> Path | None:
    """Return the log directory set by :func:`init_parent_logger`, or ``None`` if it has not run yet."""
    return _log_directory


def get_logger(name: str = application_name) -> Logger:
    """Return a stdlib logger by name."""
    return logging.getLogger(name)
