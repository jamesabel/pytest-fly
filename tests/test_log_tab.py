"""Log tab — GUI log buffering, date/time prefixes, and event capture.

Covers the :class:`GuiLogHandler` buffer, the :class:`LogTab` display, and the
end-to-end capture of admission-gate and resource-guard events.
"""

import logging
import os
import re
from pathlib import Path
from queue import Queue

import pytest

from pytest_fly.gui.log_tab import LogTab
from pytest_fly.logger import GuiLogHandler, get_logger, install_gui_log_handler
from pytest_fly.pytest_runner import admission
from pytest_fly.pytest_runner.admission import AdmissionGateConfig
from pytest_fly.pytest_runner.pytest_runner import _SingletonCoordinator, _TestRunner
from pytest_fly.pytest_runner.resource_guard import ResourceGuard, ResourceGuardConfig

# "2026-08-14 12:34:56,789 INFO ..." — stdlib asctime date/time prefix, then the level
_TIMESTAMP_PREFIX_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} [A-Z]+ ")


@pytest.fixture
def info_logger():
    """The application logger at INFO level for the duration of the test, then restored."""
    logger = get_logger()
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    yield logger
    logger.setLevel(previous_level)
    # remove any GuiLogHandler a test installed so later tests' logs are not captured
    for handler in list(logger.handlers):
        if isinstance(handler, GuiLogHandler):
            logger.removeHandler(handler)


def test_gui_log_handler_captures_with_timestamp_prefix(info_logger):
    handler = install_gui_log_handler()
    info_logger.info("hello from the test")
    info_logger.warning("a warning line")
    lines = handler.drain()
    assert len(lines) == 2
    for line in lines:
        assert _TIMESTAMP_PREFIX_REGEX.match(line), f"no date/time prefix: {line}"
    assert "INFO hello from the test" in lines[0]
    assert "WARNING a warning line" in lines[1]
    assert handler.drain() == []  # drain clears the buffer


def test_gui_log_handler_filters_debug(info_logger):
    handler = install_gui_log_handler()
    info_logger.debug("debug noise")
    info_logger.info("info signal")
    lines = handler.drain()
    assert len(lines) == 1
    assert "info signal" in lines[0]


def test_gui_log_handler_reinstall_does_not_stack(info_logger):
    install_gui_log_handler()
    handler = install_gui_log_handler()
    gui_handlers = [h for h in info_logger.handlers if isinstance(h, GuiLogHandler)]
    assert gui_handlers == [handler]


def test_log_tab_displays_drained_lines(qtbot, info_logger):
    tab = LogTab()
    qtbot.addWidget(tab)
    info_logger.info("log tab display line")
    tab.update_tick()
    text = tab._text_view.toPlainText()
    assert "log tab display line" in text
    assert _TIMESTAMP_PREFIX_REGEX.match(text.splitlines()[-1])

    tab._text_view_clear()
    assert tab._text_view.toPlainText() == ""


def test_log_tab_captures_resource_guard_trigger(qtbot, info_logger):
    """A resource-guard soft-stop trigger must show up in the Log tab with a date/time prefix."""
    tab = LogTab()
    qtbot.addWidget(tab)

    guard = ResourceGuard(
        "run-guid",
        Path("."),
        ResourceGuardConfig(enabled=True, min_free_disk_gb=10.0, commit_threshold=0.95),
        is_running_fn=lambda: True,
        soft_stop_fn=lambda: None,
        sample_interval=0.01,
        disk_free_sampler=lambda: 1.0,  # below the 10 GB minimum
        commit_sampler=lambda: 0.5,
    )
    guard.tick()
    guard.tick()  # second consecutive breach fires the trigger

    tab.update_tick()
    text = tab._text_view.toPlainText()
    assert "resource guard requesting soft stop" in text
    assert "free disk space" in text
    assert _TIMESTAMP_PREFIX_REGEX.match(text.splitlines()[-1])


def test_admission_gate_defer_is_logged(monkeypatch, info_logger):
    """An admission-gate defer episode logs its start (with the failing gates) and its admit."""
    handler = install_gui_log_handler()

    counts = [10, 10, 1]  # over ceiling twice, then drops below

    def fake_count(pid):
        return counts.pop(0) if len(counts) > 1 else counts[0]

    monkeypatch.setattr(admission, "subtree_process_count", fake_count)
    coordinator = _SingletonCoordinator()
    coordinator.acquire_normal(lambda: False, 0.01)  # _active == 1, so min-1 does not short-circuit
    runner = _TestRunner(
        "run-guid",
        Queue(),
        Path("."),
        0.01,
        coordinator,
        controller_pid=os.getpid(),
        gate_config=AdmissionGateConfig(process_count_gate_enabled=True, max_descendant_processes=2),
    )

    assert runner._await_admission(lambda: False, "tests/test_example.py") is True

    lines = handler.drain()
    defer_lines = [line for line in lines if "admission gate: deferring" in line]
    admit_lines = [line for line in lines if "admission gate: admitted" in line]
    assert len(defer_lines) == 1, f"expected exactly one defer-start line, got: {lines}"
    assert "process-count" in defer_lines[0]
    assert "tests/test_example.py" in defer_lines[0]
    assert len(admit_lines) == 1
    assert "tests/test_example.py" in admit_lines[0]
