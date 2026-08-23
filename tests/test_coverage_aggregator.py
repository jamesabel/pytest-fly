"""Tests for out-of-process coverage aggregation and the single-pass report equivalence."""

import io
import logging
import time
from pathlib import Path

import pytest
from coverage import CoverageData

from pytest_fly.file_util import sanitize_test_name
from pytest_fly.gui.coverage_tracker import CoverageTracker
from pytest_fly.interfaces import PyTestFlyExitCode, PytestProcessInfo, PytestRunnerState
from pytest_fly.pytest_runner import coverage_aggregator
from pytest_fly.pytest_runner.coverage import PytestFlyCoverage, _parse_report_totals, calculate_coverage
from pytest_fly.pytest_runner.coverage_aggregator import CoverageAggregator, aggregate_coverage
from pytest_fly.pytest_runner.run_state import PytestRunState
from pytest_fly.tick_data import TickData


def _write_fixture(data_dir: Path, test_name: str, lines: list[int]) -> Path:
    """A 4-statement source file plus one per-test coverage file covering *lines* of it."""
    source = data_dir / "m.py"
    source.write_text("a = 1\nb = 2\nc = 3\nd = 4\n")
    coverage_dir = data_dir / "coverage"
    coverage_dir.mkdir(exist_ok=True)
    data_file = coverage_dir / f"{sanitize_test_name(test_name)}.coverage"
    data = CoverageData(basename=str(data_file))
    data.add_lines({str(source.resolve()): lines})
    data.write()
    return source


def test_single_report_pass_matches_parsed_totals(tmp_path):
    """cov.report()'s return value and the parsed TOTAL line agree — the basis for the single-pass change."""
    _write_fixture(tmp_path, "tests/test_one.py", [1, 2, 3])
    value, covered, total = calculate_coverage("equiv", tmp_path, write_report=False)
    assert total == 4 and covered == 3
    assert value == pytest.approx(covered / total, abs=0.01)

    # Pin the equivalence directly against coverage's own API on the same combined file.
    cov = PytestFlyCoverage(tmp_path / "combined" / "unused.combined")
    cov.combine([str(p) for p in (tmp_path / "coverage").glob("*.coverage")], keep=True)
    buffer = io.StringIO()
    returned_pct = cov.report(ignore_errors=True, file=buffer)
    statements, missing = _parse_report_totals(buffer.getvalue())
    assert returned_pct == pytest.approx((statements - missing) / statements * 100.0, abs=1.0)


def test_child_returns_same_numbers_as_in_process(tmp_path):
    _write_fixture(tmp_path, "tests/test_one.py", [1, 2])
    in_process = calculate_coverage("current", tmp_path, write_report=False)
    out_of_process = aggregate_coverage("current", tmp_path, write_report=False, timeout=120)
    assert out_of_process == in_process
    assert out_of_process[1:] == (2, 4)


def test_child_with_no_data_returns_empty_result(tmp_path):
    assert aggregate_coverage("current", tmp_path, write_report=False, timeout=120) == (None, 0, 0)


class _DyingAggregator(CoverageAggregator):
    """Child that dies from a real segfault instead of reporting."""

    def run(self) -> None:
        import faulthandler

        faulthandler._sigsegv()  # noqa: SLF001 — documented test hook


class _HangingAggregator(CoverageAggregator):
    """Child that never reports."""

    def run(self) -> None:
        time.sleep(600)


def test_dead_child_is_a_warning_not_an_exception(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(coverage_aggregator, "CoverageAggregator", _DyingAggregator)
    with caplog.at_level(logging.WARNING):
        assert aggregate_coverage("current", tmp_path, write_report=False, timeout=120) is None
    assert any("coverage aggregation process" in r.message and "exited" in r.message for r in caplog.records)


def test_hung_child_is_terminated(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(coverage_aggregator, "CoverageAggregator", _HangingAggregator)
    with caplog.at_level(logging.WARNING):
        start = time.monotonic()
        assert aggregate_coverage("current", tmp_path, write_report=False, timeout=3) is None
    assert time.monotonic() - start < 60
    assert any("timed out" in r.message for r in caplog.records)


# --- tracker behaviour on top of the child ---------------------------------------------------


def _tick(data_dir: Path, completed: list[str], running: list[str] = ()) -> TickData:
    run_states = {}
    for name in completed:
        info = PytestProcessInfo(run_guid="run-1", name=name, pid=1, exit_code=PyTestFlyExitCode.OK, output="", time_stamp=100.0)
        run_states[name] = PytestRunState([info])
    for name in running:
        info = PytestProcessInfo(run_guid="run-1", name=name, pid=1, exit_code=PyTestFlyExitCode.NONE, output="", time_stamp=100.0)
        run_states[name] = PytestRunState([info])
    tick = TickData(process_infos=[], run_states=run_states, current_run_start=50.0)
    for name, rs in run_states.items():
        assert rs.get_state() in (PytestRunnerState.PASS, PytestRunnerState.RUNNING), (name, rs.get_state())
    return tick


def test_tracker_keeps_last_good_values_when_child_dies(tmp_path, monkeypatch):
    _write_fixture(tmp_path, "tests/test_one.py", [1, 2, 3, 4])
    tracker = CoverageTracker(tmp_path, refresh_seconds=0.0, timeout_seconds=120.0)
    tracker.update(_tick(tmp_path, ["tests/test_one.py"]))
    assert tracker.wait_for_pending()
    first = TickData(process_infos=[])
    tracker.apply_to_tick(first)
    assert first.total_lines == 4 and first.covered_lines == 4

    monkeypatch.setattr(coverage_aggregator, "CoverageAggregator", _DyingAggregator)
    _write_fixture(tmp_path, "tests/test_two.py", [1])
    tracker.update(_tick(tmp_path, ["tests/test_one.py", "tests/test_two.py"]))
    assert tracker.wait_for_pending()
    second = TickData(process_infos=[])
    tracker.apply_to_tick(second)
    assert (second.total_lines, second.covered_lines) == (first.total_lines, first.covered_lines)
    assert second.coverage_history == first.coverage_history


def test_tracker_rate_limits_and_processes_newest_set(tmp_path, monkeypatch):
    """Rapid updates inside the refresh window yield one calculation, and for the newest set."""
    processed: list[set[str]] = []

    def _record(completed, generation, run_start):
        processed.append(set(completed))
        with tracker._lock:
            tracker._last_calculation_time = time.monotonic()

    tracker = CoverageTracker(tmp_path, refresh_seconds=30.0, timeout_seconds=120.0)
    monkeypatch.setattr(tracker, "_calculate", _record)

    # First calculation goes straight through (nothing calculated yet).
    tracker.update(_tick(tmp_path, ["t1"], running=["t9"]))
    assert tracker.wait_for_pending()
    assert processed == [{"t1"}]

    # Inside the window and the run is still active: held, not calculated.
    tracker.update(_tick(tmp_path, ["t1", "t2"], running=["t9"]))
    tracker.update(_tick(tmp_path, ["t1", "t2", "t3"], running=["t9"]))
    time.sleep(0.2)
    assert processed == [{"t1"}]
    assert tracker._pending_completed == {"t1", "t2", "t3"}

    # Run finished (nothing running/queued): the hold lifts and the NEWEST set is processed.
    tracker.update(_tick(tmp_path, ["t1", "t2", "t3", "t9"]))
    assert tracker.wait_for_pending()
    assert processed == [{"t1"}, {"t1", "t2", "t3", "t9"}]


def test_tracker_zero_refresh_means_every_completion(tmp_path, monkeypatch):
    processed: list[set[str]] = []

    def _record(completed, generation, run_start):
        processed.append(set(completed))
        with tracker._lock:
            tracker._last_calculation_time = time.monotonic()

    tracker = CoverageTracker(tmp_path, refresh_seconds=0.0, timeout_seconds=120.0)
    monkeypatch.setattr(tracker, "_calculate", _record)
    for n in range(1, 4):
        tracker.update(_tick(tmp_path, [f"t{i}" for i in range(n)], running=["t9"]))
        assert tracker.wait_for_pending()
    assert len(processed) == 3
