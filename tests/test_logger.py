"""Tests for child-log rotation and stale process-monitor log purging in :mod:`pytest_fly.logger`."""

import logging
from logging.handlers import RotatingFileHandler

import pytest

import pytest_fly.logger as logger_module
from pytest_fly.logger import _purge_process_monitor_logs, configure_child_logger


@pytest.fixture
def isolated_root_logger():
    """Snapshot the root logger's handlers/level and restore them after the test.

    Both helpers under test mutate the global root logger, which would otherwise
    leak handlers into the rest of the session.
    """
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield root
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    for handler in saved_handlers:
        root.addHandler(handler)
    root.setLevel(saved_level)


def test_configure_child_logger_uses_rotating_handler(tmp_path, monkeypatch, isolated_root_logger):
    """The child handler rotates so an appended-to log can't grow without bound."""
    monkeypatch.setattr(logger_module, "_resolve_log_directory", lambda: tmp_path)

    configure_child_logger("some_test.log")

    handlers = [h for h in isolated_root_logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(handlers) == 1
    handler = handlers[0]
    assert handler.maxBytes == logger_module._MAX_BYTES
    assert handler.backupCount == logger_module._BACKUP_COUNT


def test_purge_removes_process_monitor_logs_only(tmp_path):
    """Stale process_monitor-*.log files are deleted; other logs are left intact."""
    (tmp_path / "process_monitor-123.log").write_text("", encoding="utf-8")
    (tmp_path / "process_monitor-456.log").write_text("stale\n", encoding="utf-8")
    keep_test = tmp_path / "test_norn_test_foo.py.log"
    keep_test.write_text("output\n", encoding="utf-8")
    keep_app = tmp_path / "pytest-fly.log"
    keep_app.write_text("app\n", encoding="utf-8")

    _purge_process_monitor_logs(tmp_path)

    assert not list(tmp_path.glob("process_monitor-*.log"))
    assert keep_test.is_file()
    assert keep_app.is_file()


def test_purge_skips_undeletable_file(tmp_path, monkeypatch):
    """A file that can't be unlinked (e.g. held open) is skipped, not raised."""
    (tmp_path / "process_monitor-789.log").write_text("", encoding="utf-8")

    def boom(self):
        raise OSError("locked")

    monkeypatch.setattr("pathlib.Path.unlink", boom)

    _purge_process_monitor_logs(tmp_path)  # must not raise
