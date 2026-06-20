"""Tests for the run-tab windows: FailedTestsWindow and LiveOutputWindow."""

import time
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtWidgets import QApplication

from pytest_fly.gui.gui_main import build_tick_data
from pytest_fly.gui.run_tab.failed_tests_window import FailedTestsWindow
from pytest_fly.gui.run_tab.live_output_window import LiveOutputWindow
from pytest_fly.interfaces import PyTestFlyExitCode, PytestProcessInfo
from pytest_fly.pytest_runner.live_output import live_output_path


def _info(name, pid, exit_code, time_stamp):
    return PytestProcessInfo(run_guid="g", name=name, pid=pid, exit_code=exit_code, output=None, time_stamp=time_stamp)


def _fail_tick():
    """A tick where test_b has failed and test_a passed."""
    now = time.time()
    infos = [
        _info("tests/test_a.py", 1, PyTestFlyExitCode.NONE, now - 5),
        _info("tests/test_a.py", 1, PyTestFlyExitCode.OK, now - 1),
        _info("tests/test_b.py", 2, PyTestFlyExitCode.NONE, now - 5),
        _info("tests/test_b.py", 2, PyTestFlyExitCode.TESTS_FAILED, now - 1),
    ]
    return build_tick_data(infos)


# ---------------------------------------------------------------------------
# FailedTestsWindow
# ---------------------------------------------------------------------------


def _failed_item_names(window):
    """Return the test names currently listed in a FailedTestsWindow."""
    return [window._list_widget.item(i).text() for i in range(window._list_widget.count())]


def test_failed_tests_window_empty(app):
    """No data -> empty list and a disabled copy button."""
    window = FailedTestsWindow(None)
    window.update_tick(build_tick_data([]))
    assert _failed_item_names(window) == []
    assert not window._copy_button.isEnabled()


def test_failed_tests_window_lists_failures(app):
    """A failed test is listed and the copy button is enabled."""
    window = FailedTestsWindow(None)
    window.update_tick(_fail_tick())
    names = _failed_item_names(window)
    assert "tests/test_b.py" in names
    assert "tests/test_a.py" not in names  # passing test is not listed
    assert window._copy_button.isEnabled()


def test_failed_tests_window_click_toggles_selection(app):
    """Clicking a failed test emits its name; clicking it again toggles off (emits None)."""
    window = FailedTestsWindow(None)
    window.update_tick(_fail_tick())

    emitted = []
    window.failed_test_selected.connect(emitted.append)

    item = window._list_widget.item(0)
    window._on_item_clicked(item)  # first click -> pin
    assert emitted[-1] == "tests/test_b.py"
    assert window._selected_name == "tests/test_b.py"

    window._on_item_clicked(item)  # click again -> toggle off
    assert emitted[-1] is None
    assert window._selected_name is None


def test_failed_tests_window_drops_selection_when_failure_clears(app):
    """A pinned failure that stops failing on a later tick drops the selection (emits None)."""
    window = FailedTestsWindow(None)
    window.update_tick(_fail_tick())
    emitted = []
    window.failed_test_selected.connect(emitted.append)

    window._on_item_clicked(window._list_widget.item(0))
    assert emitted[-1] == "tests/test_b.py"

    window.update_tick(build_tick_data([]))  # no failures anymore
    assert _failed_item_names(window) == []
    assert emitted[-1] is None


def test_failed_tests_window_copy_to_clipboard(app):
    """Copying puts the failed test names on the system clipboard."""
    window = FailedTestsWindow(None)
    window.update_tick(_fail_tick())
    window._copy_to_clipboard()
    assert "tests/test_b.py" in QApplication.clipboard().text()


# ---------------------------------------------------------------------------
# LiveOutputWindow
# ---------------------------------------------------------------------------


def test_live_output_window_no_running_tests(app):
    """With no running tests the selector shows the placeholder and is disabled."""
    with TemporaryDirectory() as tmp:
        window = LiveOutputWindow(None, Path(tmp))
        window.update_tick(build_tick_data([]))
        assert not window._test_selector.isEnabled()
        assert window._test_selector.currentText() == "(no tests running)"
        assert window._selected_name is None


def test_live_output_window_shows_running_test_output(app):
    """A running test populates the selector and renders its live output tail."""
    with TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        now = time.time()
        name = "tests/test_running.py"
        infos = [_info(name, 1, PyTestFlyExitCode.NONE, now - 2)]  # started, no terminal code -> RUNNING
        tick = build_tick_data(infos)

        # Write the live-output file the window will tail.
        path = live_output_path(data_dir, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("running output line\n")

        window = LiveOutputWindow(None, data_dir)
        window.update_tick(tick)

        assert window._test_selector.isEnabled()
        assert window._selected_name == name
        assert "running output line" in window._text_view.toPlainText()
        assert "Elapsed:" in window._elapsed_label.text()


def test_live_output_window_pin_failed_test(app):
    """Pinning a failed test shows its stored output and overrides the running-test view; unpinning reverts."""
    with TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        now = time.time()
        running = "tests/test_running.py"
        failed = "tests/test_failed.py"

        # A running test (drives the normal selector) and a failed test with stored output.
        running_infos = [_info(running, 1, PyTestFlyExitCode.NONE, now - 2)]
        failed_info = PytestProcessInfo(run_guid="g", name=failed, pid=2, exit_code=PyTestFlyExitCode.TESTS_FAILED, output="FAILURES\nassert 1 == 2\n", time_stamp=now - 1)
        tick = build_tick_data(running_infos + [failed_info])

        window = LiveOutputWindow(None, data_dir)
        window.update_tick(tick)
        assert window._selected_name == running  # normal running-test flow
        assert window._pinned_failed_name is None

        # Pin to the failed test.
        window.set_pinned_failed_test(failed)
        assert window._pinned_failed_name == failed
        assert "assert 1 == 2" in window._text_view.toPlainText()
        assert failed in window.title()
        assert not window._test_selector.isEnabled()

        # Unpin -> reverts to the running-test stream.
        window.set_pinned_failed_test(None)
        assert window._pinned_failed_name is None
        assert window.title() == "Live Output"
        assert window._test_selector.isEnabled()
        assert window._selected_name == running


def test_live_output_window_scroll_disables_follow_tail(app):
    """Scrolling away from the bottom turns off follow-tail."""
    with TemporaryDirectory() as tmp:
        window = LiveOutputWindow(None, Path(tmp))
        assert window._follow_tail_checkbox.isChecked()
        # Give the scrollbar a real range so a value below the maximum means "scrolled up".
        window._text_view.verticalScrollBar().setRange(0, 100)
        window._on_scroll_changed(10)  # 10 < 100 -> user scrolled away from the bottom
        assert not window._follow_tail_checkbox.isChecked()


def test_live_output_window_scroll_noop_when_follow_off(app):
    """When follow-tail is already off, a scroll event is a no-op."""
    with TemporaryDirectory() as tmp:
        window = LiveOutputWindow(None, Path(tmp))
        window._follow_tail_checkbox.setChecked(False)
        window._on_scroll_changed(0)  # must not raise or re-enable
        assert not window._follow_tail_checkbox.isChecked()
