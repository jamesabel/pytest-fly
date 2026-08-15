"""Log tab — GUI log buffering, date/time prefixes, event filtering, and persistence.

Covers the :class:`GuiLogHandler` buffer, the :class:`LogTab` display with its
Verbose/event filter, persisted view selections, the configurable line limit, and the
end-to-end capture of admission-gate and resource-guard events.
"""

import logging
import os
import re
from pathlib import Path
from queue import Queue

import pytest

from pytest_fly.gui.log_tab import LogTab
from pytest_fly.logger import EVENT_EXTRA, GuiLogHandler, get_logger, install_gui_log_handler
from pytest_fly.preferences import get_pref, log_tab_line_limit_default
from pytest_fly.pytest_runner import admission
from pytest_fly.pytest_runner.admission import AdmissionGateConfig
from pytest_fly.pytest_runner.pytest_runner import _SingletonCoordinator, _TestRunner
from pytest_fly.pytest_runner.resource_guard import ResourceGuard, ResourceGuardConfig

# "2026-08-15 12:34:56,789 INFO ..." — stdlib asctime date/time prefix, then the level
_TIMESTAMP_PREFIX_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} [A-Z]+ ")


@pytest.fixture
def info_logger():
    """The application logger at INFO level for the duration of the test, then restored.

    Also restores the Log-tab preferences (verbose, follow-tail, line limit) and removes
    any GuiLogHandler a test installed, so tests never leak state into each other.
    """
    logger = get_logger()
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    yield logger
    logger.setLevel(previous_level)
    for handler in list(logger.handlers):
        if isinstance(handler, GuiLogHandler):
            logger.removeHandler(handler)
    pref = get_pref()
    pref.log_tab_verbose = False
    pref.log_tab_follow_tail = True
    pref.log_tab_line_limit = log_tab_line_limit_default


def test_gui_log_handler_captures_with_timestamp_prefix(info_logger):
    handler = install_gui_log_handler()
    info_logger.info("hello from the test")
    info_logger.warning("a warning line")
    records = handler.drain()
    assert len(records) == 2
    for record in records:
        assert _TIMESTAMP_PREFIX_REGEX.match(record.line), f"no date/time prefix: {record.line}"
    assert "INFO hello from the test" in records[0].line
    assert records[0].levelno == logging.INFO
    assert records[0].event is False
    assert "WARNING a warning line" in records[1].line
    assert records[1].levelno == logging.WARNING
    assert handler.drain() == []  # drain clears the buffer


def test_gui_log_handler_event_tagging(info_logger):
    handler = install_gui_log_handler()
    info_logger.info("plain info")
    info_logger.info("notable event", extra=EVENT_EXTRA)
    records = handler.drain()
    assert [record.event for record in records] == [False, True]


def test_gui_log_handler_filters_debug(info_logger):
    handler = install_gui_log_handler()
    info_logger.debug("debug noise")
    info_logger.info("info signal")
    records = handler.drain()
    assert len(records) == 1
    assert "info signal" in records[0].line


def test_gui_log_handler_reinstall_does_not_stack(info_logger):
    install_gui_log_handler()
    handler = install_gui_log_handler()
    gui_handlers = [h for h in info_logger.handlers if isinstance(h, GuiLogHandler)]
    assert gui_handlers == [handler]


def test_log_tab_default_filter_events_and_warnings_only(qtbot, info_logger):
    """Verbose off (the default): tagged events and warnings show; plain INFO does not."""
    tab = LogTab()
    qtbot.addWidget(tab)
    assert tab._verbose_checkbox.isChecked() is False

    info_logger.info("plain info chatter")
    info_logger.info("admission gate style event", extra=EVENT_EXTRA)
    info_logger.warning("an important warning")
    tab.update_tick()

    text = tab._text_view.toPlainText()
    assert "plain info chatter" not in text
    assert "admission gate style event" in text
    assert "an important warning" in text
    assert _TIMESTAMP_PREFIX_REGEX.match(text.splitlines()[-1])


def test_log_tab_verbose_shows_everything_retroactively(qtbot, info_logger):
    """Toggling Verbose on rebuilds the view from history, revealing previously hidden lines."""
    tab = LogTab()
    qtbot.addWidget(tab)

    info_logger.info("hidden until verbose")
    tab.update_tick()
    assert "hidden until verbose" not in tab._text_view.toPlainText()

    tab._verbose_checkbox.setChecked(True)
    assert "hidden until verbose" in tab._text_view.toPlainText()

    tab._verbose_checkbox.setChecked(False)
    assert "hidden until verbose" not in tab._text_view.toPlainText()


def test_log_tab_selections_persist(qtbot, info_logger):
    """Verbose and Follow-tail selections are saved to preferences and restored on rebuild."""
    tab = LogTab()
    qtbot.addWidget(tab)
    tab._verbose_checkbox.setChecked(True)
    tab._follow_tail_checkbox.setChecked(False)
    assert get_pref().log_tab_verbose is True
    assert get_pref().log_tab_follow_tail is False

    restored = LogTab()
    qtbot.addWidget(restored)
    assert restored._verbose_checkbox.isChecked() is True
    assert restored._follow_tail_checkbox.isChecked() is False


def test_log_tab_line_limit_from_preferences(qtbot, info_logger):
    """The Configuration-tab line limit bounds the history, including mid-session changes."""
    get_pref().log_tab_line_limit = 5
    tab = LogTab()
    qtbot.addWidget(tab)
    assert tab._text_view.maximumBlockCount() == 5

    for i in range(8):
        info_logger.info(f"event line {i}", extra=EVENT_EXTRA)
    tab.update_tick()
    assert len(tab._history) == 5
    lines = tab._text_view.toPlainText().splitlines()
    assert len(lines) == 5
    assert "event line 7" in lines[-1]  # newest retained; oldest dropped

    get_pref().log_tab_line_limit = 3  # shrink mid-session; applied on the next tick
    tab.update_tick()
    assert len(tab._history) == 3
    assert tab._text_view.maximumBlockCount() == 3


def test_log_tab_clear_also_clears_history(qtbot, info_logger):
    tab = LogTab()
    qtbot.addWidget(tab)
    info_logger.warning("about to be cleared")
    tab.update_tick()
    assert "about to be cleared" in tab._text_view.toPlainText()

    tab._text_view_clear()
    assert tab._text_view.toPlainText() == ""
    tab._verbose_checkbox.setChecked(True)  # rebuild from (now empty) history
    assert tab._text_view.toPlainText() == ""


def test_log_tab_captures_resource_guard_trigger(qtbot, info_logger):
    """A resource-guard trigger (WARNING) must show in the default view with a date/time prefix."""
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


def test_admission_gate_defer_is_logged_as_event(monkeypatch, info_logger):
    """An admission-gate defer episode logs its start and admit, tagged as run events."""
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

    records = handler.drain()
    defer_records = [record for record in records if "admission gate: deferring" in record.line]
    admit_records = [record for record in records if "admission gate: admitted" in record.line]
    assert len(defer_records) == 1, f"expected exactly one defer-start line, got: {[r.line for r in records]}"
    assert "process-count" in defer_records[0].line
    assert "tests/test_example.py" in defer_records[0].line
    assert defer_records[0].event is True, "admission-gate defer must be tagged as a run event"
    assert len(admit_records) == 1
    assert admit_records[0].event is True
