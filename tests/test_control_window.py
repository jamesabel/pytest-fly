"""Tests for ControlWindow button-state and stop wiring (excludes the subprocess-spawning run())."""

from pytest_fly.gui.run_tab.control_window import ControlWindow

from .paths import get_temp_dir


class _FakeRunner:
    """Minimal stand-in for PytestRunner exposing the methods ControlWindow calls."""

    def __init__(self):
        self.soft_stopped = False
        self.stopped = False
        self.cancel_calls = 0
        self.cancel_result = True
        self._running = True
        self._user_complete = False

    def is_running(self):
        return self._running

    def is_user_complete(self):
        return self._user_complete

    def soft_stop(self):
        self.soft_stopped = True

    def cancel_soft_stop(self):
        self.cancel_calls += 1
        return self.cancel_result

    def stop(self):
        self.stopped = True

    def force_stop_and_reset(self):
        # Mirrors PytestRunner.force_stop_and_reset: stop + reset to a completed state.
        self.stopped = True
        self._user_complete = True


def test_refresh_button_state_no_runner(app):
    """With no runner, Run is enabled and the stop buttons are disabled."""
    cw = ControlWindow(None, get_temp_dir("control_none"))
    cw.refresh_button_state()
    assert cw.run_button.isEnabled()
    assert not cw.stop_button.isEnabled()
    assert not cw.force_stop_button.isEnabled()


def test_button_states_running_and_stops(app):
    """Running -> stop/force enabled; soft_stop and force_stop drive the runner and button states."""
    cw = ControlWindow(None, get_temp_dir("control_run"))
    runner = _FakeRunner()
    cw.pytest_runner = runner

    cw.refresh_button_state()  # running, not soft-stopped
    assert not cw.run_button.isEnabled()
    assert cw.stop_button.isEnabled()
    assert cw.force_stop_button.isEnabled()

    cw.soft_stop()
    assert runner.soft_stopped is True
    assert cw._soft_stop_requested is True
    assert cw.stop_button.text() == "Cancel Stop"

    cw.refresh_button_state()  # soft-stop-requested branch: stop button stays enabled as Cancel Stop
    assert cw.stop_button.isEnabled()
    assert cw.stop_button.text() == "Cancel Stop"
    assert cw.force_stop_button.isEnabled()

    cw.force_stop()
    assert runner.stopped is True
    assert cw.run_button.isEnabled()
    assert cw.stop_button.text() == "Stop"
    assert cw.run_guid is None


def test_cancel_soft_stop(app):
    """Clicking the stop button while a soft stop is pending cancels it and restores the Stop label."""
    cw = ControlWindow(None, get_temp_dir("control_cancel"))
    runner = _FakeRunner()
    cw.pytest_runner = runner

    cw.soft_stop()
    assert cw.stop_button.text() == "Cancel Stop"

    cw._on_stop_clicked()  # acts as Cancel Stop while a soft stop is pending
    assert runner.cancel_calls == 1
    assert cw._soft_stop_requested is False
    assert cw.stop_button.text() == "Stop"

    cw.refresh_button_state()  # back to the plain running state
    assert cw.stop_button.isEnabled()
    assert cw.stop_button.text() == "Stop"

    cw._on_stop_clicked()  # acts as Stop again
    assert cw._soft_stop_requested is True


def test_cancel_soft_stop_too_late(app):
    """If the runner reports the cancel came too late, the pending state is left for refresh to settle."""
    cw = ControlWindow(None, get_temp_dir("control_cancel_late"))
    runner = _FakeRunner()
    runner.cancel_result = False
    cw.pytest_runner = runner

    cw.soft_stop()
    cw.cancel_soft_stop()
    assert runner.cancel_calls == 1
    assert cw._soft_stop_requested is True  # cancel refused; refresh_button_state settles once the run completes

    runner._user_complete = True
    cw.refresh_button_state()
    assert cw.run_button.isEnabled()
    assert cw._soft_stop_requested is False
    assert cw.stop_button.text() == "Stop"
