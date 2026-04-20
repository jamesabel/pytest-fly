"""Tests for gui.coverage_tracker.CoverageTracker."""

from pathlib import Path
from tempfile import TemporaryDirectory

from coverage import CoverageData

from pytest_fly.file_util import sanitize_test_name
from pytest_fly.gui.coverage_tracker import CoverageTracker
from pytest_fly.interfaces import PyTestFlyExitCode, PytestProcessInfo
from pytest_fly.pytest_runner.pytest_runner import PytestRunState
from pytest_fly.tick_data import TickData


def _make_tick(passed_names: list[str], data_dir: Path) -> TickData:
    """Build a TickData where each named test is in the PASS state."""
    run_states = {}
    for name in passed_names:
        info = PytestProcessInfo(
            run_guid="run-1",
            name=name,
            pid=1234,
            exit_code=PyTestFlyExitCode.OK,
            output="",
            time_stamp=100.0,
        )
        run_states[name] = PytestRunState([info])
    return TickData(process_infos=[], run_states=run_states, current_run_start=50.0)


def _write_per_test_coverage(test_name: str, source_file: Path, lines: list[int], coverage_dir: Path) -> None:
    coverage_dir.mkdir(parents=True, exist_ok=True)
    safe = sanitize_test_name(test_name)
    data_file = coverage_dir / f"{safe}.coverage"
    data_file.unlink(missing_ok=True)
    data = CoverageData(basename=str(data_file))
    data.add_lines({str(source_file): lines})
    data.write()


def test_tracker_initial_state():
    with TemporaryDirectory() as tmp:
        tracker = CoverageTracker(Path(tmp))
        tick = _make_tick([], Path(tmp))
        tracker.apply_to_tick(tick)
        assert tick.coverage_history == []
        assert tick.per_test_coverage == {}
        assert tick.covered_lines == 0
        assert tick.total_lines == 0


def test_handle_new_run_resets_state():
    """Passing a new GUID must clear accumulated state."""
    with TemporaryDirectory() as tmp:
        tracker = CoverageTracker(Path(tmp))
        tracker._completed_tests = {"stale"}
        tracker._coverage_history = [(1.0, 0.5)]
        tracker._per_test_coverage = {"stale": 0.5}
        tracker._covered_lines = 42
        tracker._total_lines = 100
        tracker._last_run_guid = "old-guid"

        tracker.handle_new_run("new-guid")

        assert tracker._completed_tests == set()
        assert tracker._coverage_history == []
        assert tracker._per_test_coverage == {}
        assert tracker._covered_lines == 0
        assert tracker._total_lines == 0
        assert tracker._last_run_guid == "new-guid"


def test_handle_new_run_noop_when_same_guid():
    with TemporaryDirectory() as tmp:
        tracker = CoverageTracker(Path(tmp))
        tracker._last_run_guid = "same"
        tracker._completed_tests = {"keep"}

        tracker.handle_new_run("same")

        assert tracker._completed_tests == {"keep"}


def test_update_records_coverage_for_completed_tests():
    """When tests complete, update() recalculates combined + per-test coverage."""
    with TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        coverage_dir = data_dir / "coverage"

        src = data_dir / "m.py"
        src.write_text("a = 1\nb = 2\nc = 3\nd = 4\n")

        test_name = "tests/test_one.py"
        _write_per_test_coverage(test_name, src, [1, 2, 3, 4], coverage_dir)

        tracker = CoverageTracker(data_dir)
        tick = _make_tick([test_name], data_dir)
        tracker.update(tick)
        tracker.apply_to_tick(tick)

        # Coverage history seeded + one current-tick data point.
        assert len(tick.coverage_history) >= 1
        for ts, pct in tick.coverage_history:
            assert 0.0 <= pct <= 1.0
            assert ts > 0.0


def test_update_skips_when_no_new_completions():
    """Re-invoking update with the same completed set doesn't grow history forever."""
    with TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        tracker = CoverageTracker(data_dir)
        tick = _make_tick([], data_dir)

        tracker.update(tick)
        tracker.update(tick)
        tracker.apply_to_tick(tick)

        assert tick.coverage_history == []
