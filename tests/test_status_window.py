"""Tests for the run-tab StatusWindow aggregate-summary logic."""

import time

from pytest_fly.gui.gui_main import build_tick_data
from pytest_fly.gui.run_tab.status_window import StatusWindow
from pytest_fly.interfaces import PutVersionInfo, PyTestFlyExitCode, PytestProcessInfo


def _info(name, pid, exit_code, ts):
    return PytestProcessInfo(run_guid="g", name=name, pid=pid, exit_code=exit_code, output=None, time_stamp=ts)


def _put(dirty=False):
    return PutVersionInfo(name="pkg", version="1.0", source="pyproject", git_describe=None, git_sha="abc1234", git_branch="main", git_dirty=dirty, project_root="/x")


def test_status_window_complete_all_pass(app):
    """An all-passing completed run turns the pass-rate label green."""
    window = StatusWindow(None)
    tick = build_tick_data([_info("test_p.py", 1, PyTestFlyExitCode.OK, time.time())])
    window.update_tick(tick)
    assert "green" in window.pass_rate_label.styleSheet()


def test_status_window_complete_with_failure(app):
    """A completed run with a failure turns the pass-rate label red."""
    now = time.time()
    infos = [_info("test_p.py", 1, PyTestFlyExitCode.OK, now), _info("test_f.py", 2, PyTestFlyExitCode.TESTS_FAILED, now)]
    window = StatusWindow(None)
    window.update_tick(build_tick_data(infos))
    assert "red" in window.pass_rate_label.styleSheet()


def test_status_window_running_calculating_pass_rate(app):
    """While a test is running with no completions, pass rate shows '(calculating...)'."""
    window = StatusWindow(None)
    tick = build_tick_data([_info("test_a.py", 1, PyTestFlyExitCode.NONE, time.time())])
    window.update_tick(tick)
    assert "calculating" in window.pass_rate_label.text()


def test_status_window_rich_tick_with_soft_stop(app):
    """A rich tick exercises PUT line, coverage, parallelism, ETA, and soft-stop messaging."""
    now = time.time()
    infos = [
        _info("test_run.py", None, PyTestFlyExitCode.NONE, now - 3),
        _info("test_run.py", 1, PyTestFlyExitCode.NONE, now - 2),  # running
        _info("test_q.py", None, PyTestFlyExitCode.NONE, now),  # queued
        _info("test_p.py", 2, PyTestFlyExitCode.OK, now - 1),  # passed
    ]
    tick = build_tick_data(infos)
    tick.put_version_info = _put(dirty=True)
    tick.prior_durations = {"test_run.py": 10.0, "test_q.py": 5.0}
    tick.soft_stop_requested = True
    tick.num_processes = 2
    tick.average_parallelism = 1.5
    tick.coverage_history = [(now - 5, 0.5)]
    tick.total_lines = 100
    tick.covered_lines = 50
    tick.min_time_stamp_started = now - 5
    tick.max_time_stamp_started = now

    window = StatusWindow(None)
    window.update_tick(tick)
    text = window.status_widget.toPlainText()

    assert "PUT: pkg 1.0" in text
    assert "uncommitted changes" in text
    assert "Coverage: 50.0%" in text
    assert "Avg parallelism: 1.5x" in text
    assert "Total time:" in text
    assert "Estimated remaining:" in text
    assert "Stopping" in text
    assert "Estimated finish:" in text


def test_status_window_resource_guard_banner(app):
    """A triggered resource guard shows the low-resources banner; canceled stop changes the wording."""
    from pytest_fly.pytest_runner.resource_guard import ResourceGuardInfo

    now = time.time()
    tick = build_tick_data([_info("test_a.py", 1, PyTestFlyExitCode.NONE, now)])
    tick.resource_guard_info = ResourceGuardInfo(triggered=True, reason="free disk space 2.5 GB is below the 10 GB minimum", free_disk_gb=2.5, commit_fraction=0.5)
    tick.soft_stop_requested = True

    window = StatusWindow(None)
    window.update_tick(tick)
    assert window.stall_banner_label.isVisibleTo(window)
    assert "Low system resources" in window.stall_banner_label.text()
    assert "Cancel Stop" in window.stall_banner_label.text()

    # After the user cancels the soft stop, the banner reports the trigger without "stopping" text.
    tick.soft_stop_requested = False
    window.update_tick(tick)
    assert window.stall_banner_label.isVisibleTo(window)
    assert "automatic stop" in window.stall_banner_label.text()
    assert "Cancel Stop" not in window.stall_banner_label.text()

    # An untriggered guard renders no banner.
    tick.resource_guard_info = ResourceGuardInfo(triggered=False)
    window.update_tick(tick)
    assert not window.stall_banner_label.isVisibleTo(window)


def test_status_window_empty_with_put_info(app):
    """The no-tests-yet branch still renders the PUT line."""
    tick = build_tick_data([])
    tick.put_version_info = _put(dirty=True)
    window = StatusWindow(None)
    window.update_tick(tick)
    text = window.status_widget.toPlainText()
    assert "PUT: pkg" in text
    assert "uncommitted changes" in text
    assert "press Run" in text


def test_status_window_preparing_run_message(app):
    """While run preparation is in flight (no records yet), show the please-wait status, not the Run prompt."""
    window = StatusWindow(None)
    tick = build_tick_data([])
    tick.run_prep_active = True
    window.update_tick(tick)
    assert "please wait" in window.status_widget.toPlainText()
    assert "press Run" not in window.status_widget.toPlainText()
    assert window.progress_bar.maximum() == 0  # indeterminate busy indicator
    assert "preparing" in window.complete_label.text()

    # Preparation finished with no run (aborted/failed): back to the idle prompt and determinate bar.
    tick.run_prep_active = False
    window.update_tick(tick)
    assert "press Run" in window.status_widget.toPlainText()
    assert window.progress_bar.maximum() == 100


def test_status_window_preparing_with_resume_copies(app):
    """RESUME preparation copies records in before the runner starts — still say preparing."""
    window = StatusWindow(None)
    tick = build_tick_data([_info("test_p.py", 1, PyTestFlyExitCode.OK, time.time())])
    tick.run_prep_active = True
    window.update_tick(tick)
    assert "please wait" in window.status_widget.toPlainText()
    assert window.progress_bar.maximum() == 100  # counts are real, keep the determinate bar
