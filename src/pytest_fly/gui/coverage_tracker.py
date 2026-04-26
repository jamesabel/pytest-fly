"""
Tracks combined and per-test code coverage across a test run.

Extracted from :class:`FlyAppMainWindow` to keep coverage bookkeeping
separate from the GUI window lifecycle.  The main window creates one
instance and calls :meth:`CoverageTracker.update` on each refresh tick.
"""

import time
from pathlib import Path

from coverage import Coverage

from ..file_util import sanitize_test_name
from ..interfaces import PytestRunnerState
from ..logger import get_logger
from ..pytest_runner.coverage import calculate_coverage
from ..tick_data import TickData

log = get_logger()


class CoverageTracker:
    """Maintains cumulative coverage state and updates it when new tests finish.

    :param data_dir: Application data directory containing the ``coverage/`` subdirectory.
    """

    def __init__(self, data_dir: Path):
        self._data_dir = data_dir
        self._completed_tests: set[str] = set()
        self._coverage_history: list[tuple[float, float]] = []
        self._per_test_coverage: dict[str, float] = {}
        self._covered_lines: int = 0
        self._total_lines: int = 0
        self._last_run_guid: str | None = None

    def handle_new_run(self, current_guid: str | None) -> None:
        """Reset in-memory coverage state when a new run starts.

        File-system cleanup of stale coverage data is done synchronously by
        ``ControlWindow.run`` *before* the new ``PytestRunner`` is started — doing
        it here on a periodic tick can race with PytestProcess coverage writes
        that are still in flight, deleting the directory mid-``coverage.save()``.

        :param current_guid: The GUID of the current run.
        """
        if current_guid != self._last_run_guid:
            self._last_run_guid = current_guid
            self._completed_tests = set()
            self._coverage_history = []
            self._per_test_coverage = {}
            self._covered_lines = 0
            self._total_lines = 0

    def update(self, tick: TickData) -> None:
        """Recalculate combined and per-test coverage when new tests complete.

        :param tick: Pre-computed data for this refresh cycle.
        """
        current_completed = {name for name, rs in tick.run_states.items() if rs.get_state() in (PytestRunnerState.PASS, PytestRunnerState.FAIL)}
        if current_completed and current_completed != self._completed_tests:
            self._completed_tests = current_completed
            try:
                coverage_pct, self._covered_lines, self._total_lines = calculate_coverage("current", self._data_dir, write_report=False)
                if coverage_pct is not None:
                    # Seed the first data point at current_run_start so the chart always has
                    # at least two points — needed for a visible line/fill, especially in RESUME
                    # mode when no new tests run and only one calculation happens this run.
                    if not self._coverage_history and tick.current_run_start is not None:
                        self._coverage_history.append((tick.current_run_start, coverage_pct))
                    self._coverage_history.append((time.time(), coverage_pct))
            except Exception as e:
                log.warning(f"coverage calculation failed: {e}")

            # Recompute per-test coverage for ALL completed tests since the denominator
            # (total_lines) may have changed as new tests discover new source files.
            if self._total_lines > 0:
                coverage_dir = Path(self._data_dir, "coverage")
                for test_name in self._completed_tests:
                    safe_name = sanitize_test_name(test_name)
                    cov_file = coverage_dir / f"{safe_name}.coverage"
                    if cov_file.exists():
                        try:
                            cov = Coverage(cov_file)
                            cov.load()
                            data = cov.get_data()
                            executed = sum(len(data.lines(f) or []) for f in data.measured_files())
                            self._per_test_coverage[test_name] = executed / self._total_lines
                        except Exception as e:
                            log.info(f"per-test coverage for {test_name} failed: {e}")

    def apply_to_tick(self, tick: TickData) -> None:
        """Stamp the current coverage state onto *tick* so tabs can read it.

        :param tick: The tick data bundle to update in-place.
        """
        tick.coverage_history = self._coverage_history
        tick.per_test_coverage = self._per_test_coverage
        tick.covered_lines = self._covered_lines
        tick.total_lines = self._total_lines
