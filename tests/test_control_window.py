"""Tests for ControlWindow button-state and stop wiring (excludes the subprocess-spawning run())."""

from pytest_fly.gui.run_tab.control_window import ControlWindow

from .paths import get_temp_dir


class _FakeRunner:
    """Minimal stand-in for PytestRunner exposing the methods ControlWindow calls."""

    def __init__(self):
        self.soft_stopped = False
        self.stopped = False
        self._running = True
        self._user_complete = False

    def is_running(self):
        return self._running

    def is_user_complete(self):
        return self._user_complete

    def soft_stop(self):
        self.soft_stopped = True

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

    cw.refresh_button_state()  # soft-stop-requested branch
    assert not cw.stop_button.isEnabled()
    assert cw.force_stop_button.isEnabled()

    cw.force_stop()
    assert runner.stopped is True
    assert cw.run_button.isEnabled()
    assert cw.run_guid is None
