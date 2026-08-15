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
from collections import deque
from dataclasses import dataclass
from logging import Formatter, Logger
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock

from pytest_fly.__version__ import application_name
from pytest_fly.paths import get_log_dir

_LOG_FORMAT = "%(asctime)s %(process)d %(name)s %(levelname)s %(message)s"
# GUI Log tab format — same date/time prefix as the file log, but no PID/logger name
# (every captured record comes from this process's application logger).
_GUI_LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
_MAX_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 5
_GUI_LOG_MAX_RECORDS = 10_000  # bound on buffered-but-not-yet-drained GUI log lines

_log_directory: Path | None = None


def _resolve_log_directory() -> Path:
    """Workspace-local log directory (``<workspace>/.pytest-fly/logs/``), shared by parent and spawn children.

    Spawn children re-import this module without the parent's in-process workspace binding,
    but :func:`pytest_fly.paths.get_log_dir` falls back to the inherited ``PYTEST_FLY_WORKSPACE``
    environment variable, so they resolve the same directory.
    """
    return get_log_dir()


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


# Pass as ``extra=`` on a log call to mark the record as a notable run *event* — something
# the Log tab shows even in its default (non-verbose) view, e.g. an admission gate deferring
# dispatch or the resource guard requesting a stop.  Warnings and errors always show.
EVENT_EXTRA = {"fly_event": True}


@dataclass(frozen=True)
class GuiLogRecord:
    """One captured log record, pre-formatted for the GUI Log tab."""

    line: str  # formatted line, including the date/time prefix
    levelno: int  # stdlib logging level number (logging.INFO, logging.WARNING, ...)
    event: bool  # True when logged with extra=EVENT_EXTRA — a notable run event


class GuiLogHandler(logging.Handler):
    """Buffers formatted log records for display in the GUI Log tab.

    Records may be emitted from any thread (worker threads, monitor threads); the GUI
    thread calls :meth:`drain` on its refresh tick to collect the new records.  The
    buffer is bounded so a chatty logger can never grow memory without bound if the GUI
    stops draining.
    """

    def __init__(self, level: int = logging.INFO) -> None:
        super().__init__(level)
        self.setFormatter(Formatter(_GUI_LOG_FORMAT))
        self._buffer_lock = Lock()
        self._buffer: deque[GuiLogRecord] = deque(maxlen=_GUI_LOG_MAX_RECORDS)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except (ValueError, TypeError):
            return  # malformed record — never let the log view take down logging
        gui_record = GuiLogRecord(line=line, levelno=record.levelno, event=bool(getattr(record, "fly_event", False)))
        with self._buffer_lock:
            self._buffer.append(gui_record)

    def drain(self) -> list[GuiLogRecord]:
        """Return all buffered records (oldest first) and clear the buffer."""
        with self._buffer_lock:
            records = list(self._buffer)
            self._buffer.clear()
        return records


def install_gui_log_handler() -> GuiLogHandler:
    """Attach a fresh :class:`GuiLogHandler` to the application logger and return it.

    Attached to the application logger (not root) so the Log tab shows pytest-fly's own
    events without third-party library noise.  Any previously installed instance is
    removed first, so repeated installation (e.g. widget re-creation in tests) never
    stacks handlers.
    """
    app_logger = get_logger()
    for handler in list(app_logger.handlers):
        if isinstance(handler, GuiLogHandler):
            app_logger.removeHandler(handler)
    handler = GuiLogHandler()
    app_logger.addHandler(handler)
    return handler
