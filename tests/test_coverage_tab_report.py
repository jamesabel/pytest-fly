"""Tests for the CoverageTab 'View HTML Report' button wiring."""

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


def test_view_report_generates_html_and_opens_viewer(app, monkeypatch):
    """Clicking generates a fresh HTML report (write_report=True) then opens it."""
    calls = {}

    def _fake_calculate(identifier, data_dir, write_report):
        calls["calc"] = (identifier, data_dir, write_report)
        return 0.5, 50, 100

    class _FakeViewer:
        def __init__(self, data_dir):
            calls["viewer_dir"] = data_dir

        def view(self):
            calls["viewed"] = True

    monkeypatch.setattr(coverage_tab_module, "calculate_coverage", _fake_calculate)
    monkeypatch.setattr(coverage_tab_module, "ViewCoverage", _FakeViewer)

    with TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        tab = CoverageTab(data_dir)
        tab._on_view_report()

    assert calls["calc"][0] == "html_report"  # dedicated identifier, not the live tracker's "current"
    assert calls["calc"][1] == data_dir
    assert calls["calc"][2] is True  # write_report
    assert calls["viewer_dir"] == data_dir
    assert calls["viewed"] is True


def test_view_report_graceful_with_no_coverage_data(app, monkeypatch):
    """With no coverage data on disk the handler must not raise and must not open a browser."""
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda uri: opened.append(uri))
    with TemporaryDirectory() as tmp:
        tab = CoverageTab(Path(tmp))
        tab._on_view_report()  # empty data dir -> no report produced
    assert opened == []
