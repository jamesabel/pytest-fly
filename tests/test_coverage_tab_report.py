"""Tests for the CoverageTab 'View HTML Report' button wiring."""

import time
import webbrowser
from pathlib import Path
from tempfile import TemporaryDirectory

from pytest_fly.gui.coverage_tab import CoverageTab
from pytest_fly.gui.coverage_tab import coverage_tab as coverage_tab_module
from pytest_fly.tick_data import TickData


def test_no_button_without_data_dir(app):
    """Without a data_dir the report button is omitted entirely."""
    tab = CoverageTab()
    assert tab.view_report_button is None


def test_button_present_but_disabled_without_data(app):
    """With a data_dir the button exists but is disabled until there is coverage data."""
    with TemporaryDirectory() as tmp:
        tab = CoverageTab(Path(tmp))
        assert tab.view_report_button is not None
        assert not tab.view_report_button.isEnabled()


def test_button_enables_only_when_coverage_data_present(app):
    """update_tick enables the button when total_lines > 0 and disables it otherwise."""
    with TemporaryDirectory() as tmp:
        tab = CoverageTab(Path(tmp))
        tab.update_tick(TickData(process_infos=[], total_lines=120, covered_lines=90))
        assert tab.view_report_button.isEnabled()
        tab.update_tick(TickData(process_infos=[], total_lines=0))
        assert not tab.view_report_button.isEnabled()


def _pump_until_report_done(app, tab: CoverageTab, timeout: float = 60.0) -> None:
    """Drive the Qt event loop until the tab's report child has been reaped by the poll timer."""
    deadline = time.monotonic() + timeout
    while tab._report_child is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    assert tab._report_child is None, "HTML report child did not finish"


class _FakeAggregator:
    """Stand-in for CoverageAggregator: records its arguments and completes immediately."""

    calls: dict = {}

    def __init__(self, identifier, data_dir, write_report):
        _FakeAggregator.calls["calc"] = (identifier, data_dir, write_report)
        self.exitcode = 0
        self.pid = 0

    def start(self):
        pass

    def is_alive(self):
        return False

    def join(self, timeout=None):
        pass

    def terminate(self):
        pass

    def result(self):
        return 0.5, 50, 100


def test_view_report_generates_html_and_opens_viewer(app, monkeypatch):
    """Clicking generates a fresh HTML report (write_report=True) in the aggregator child, then opens it."""
    calls = _FakeAggregator.calls
    calls.clear()

    class _FakeViewer:
        def __init__(self, data_dir):
            calls["viewer_dir"] = data_dir

        def view(self):
            calls["viewed"] = True
            return True  # report found and opened — no warning dialog

    monkeypatch.setattr(coverage_tab_module, "CoverageAggregator", _FakeAggregator)
    monkeypatch.setattr(coverage_tab_module, "ViewCoverage", _FakeViewer)

    with TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        tab = CoverageTab(data_dir)
        tab._on_view_report()
        assert not tab.view_report_button.isEnabled()  # disabled while generating
        _pump_until_report_done(app, tab)

    assert calls["calc"][0] == "html_report"  # dedicated identifier, not the live tracker's "current"
    assert calls["calc"][1] == data_dir
    assert calls["calc"][2] is True  # write_report
    assert calls["viewer_dir"] == data_dir
    assert calls["viewed"] is True
    assert tab.view_report_button.text() == "View HTML Report"


def test_view_report_graceful_with_no_coverage_data(app, monkeypatch):
    """With no coverage data on disk the handler warns the user (no browser, no exception).

    Uses the real aggregator child process end to end.
    """
    opened = []
    warnings = []
    monkeypatch.setattr(webbrowser, "open", lambda uri: opened.append(uri))
    # The missing-report path now tells the user via a (modal) warning dialog — stub it out.
    monkeypatch.setattr(coverage_tab_module.QMessageBox, "warning", lambda *args: warnings.append(args))
    with TemporaryDirectory() as tmp:
        tab = CoverageTab(Path(tmp))
        tab._on_view_report()  # empty data dir -> no report produced
        _pump_until_report_done(app, tab)
    assert opened == []
    assert len(warnings) == 1  # the user is told there was no report to open
