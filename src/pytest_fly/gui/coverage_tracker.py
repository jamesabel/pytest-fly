"""
Tracks combined and per-test code coverage across a test run.

Extracted from :class:`FlyAppMainWindow` to keep coverage bookkeeping
separate from the GUI window lifecycle.  The main window creates one
instance and calls :meth:`CoverageTracker.update` on each refresh tick.

Coverage combination is expensive — it re-combines every per-test ``.coverage``
file and runs two full report passes over the PUT's sources — so it runs on a
dedicated background thread.  :meth:`update` only *submits* work (coalescing:
the worker always processes the latest completed-test set) and
:meth:`apply_to_tick` publishes the most recently finished results, so the GUI
tick never blocks on coverage.
"""

import time
from pathlib import Path
from threading import Event, Lock, Thread

from coverage import Coverage

from ..file_util import sanitize_test_name
from ..interfaces import PytestRunnerState
from ..logger import get_logger
from ..pytest_runner.coverage import COVERAGE_READ_ERRORS, calculate_coverage
from ..tick_data import TickData

log = get_logger()


class CoverageTracker:
    """Maintains cumulative coverage state and updates it when new tests finish.

    :param data_dir: Application data directory containing the ``coverage/`` subdirectory.
    """

    def __init__(self, data_dir: Path):
        self._data_dir = data_dir
        self._last_run_guid: str | None = None
        self._worker: Thread | None = None
        self._work_available = Event()

        self._lock = Lock()
        # All state below is guarded by _lock (shared between the GUI thread and the worker).
        self._pending_completed: set[str] | None = None  # newest submitted completed-test set awaiting the worker; None when nothing pending
        self._submitted_completed: set[str] = set()  # last completed-test set submitted, to skip no-change ticks
        self._current_run_start: float | None = None
        self._calculating = False
        self._generation = 0  # bumped by handle_new_run so an in-flight calculation for a prior run is discarded
        self._coverage_history: list[tuple[float, float]] = []
        self._per_test_coverage: dict[str, float] = {}
        self._covered_lines: int = 0
        self._total_lines: int = 0

    def handle_new_run(self, current_guid: str | None) -> None:
        """Reset coverage state when a new run starts.

        File-system cleanup of stale coverage data is done synchronously by
        ``ControlWindow`` run preparation *before* the new ``PytestRunner`` is started —
        doing it here on a periodic tick can race with PytestProcess coverage writes
        that are still in flight, deleting the directory mid-``coverage.save()``.

        :param current_guid: The GUID of the current run.
        """
        if current_guid != self._last_run_guid:
            self._last_run_guid = current_guid
            with self._lock:
                self._generation += 1
                self._pending_completed = None
                self._submitted_completed = set()
                self._coverage_history = []
                self._per_test_coverage = {}
                self._covered_lines = 0
                self._total_lines = 0

    def update(self, tick: TickData) -> None:
        """Submit a recalculation to the worker when the completed-test set changed.

        :param tick: Pre-computed data for this refresh cycle.
        """
        current_completed = {name for name, rs in tick.run_states.items() if rs.get_state() in (PytestRunnerState.PASS, PytestRunnerState.FAIL)}
        if not current_completed:
            return
        with self._lock:
            if current_completed == self._submitted_completed:
                return
            self._submitted_completed = set(current_completed)
            self._pending_completed = set(current_completed)
            self._current_run_start = tick.current_run_start
        self._ensure_worker()
        self._work_available.set()

    def apply_to_tick(self, tick: TickData) -> None:
        """Stamp the most recently computed coverage state onto *tick* so tabs can read it.

        Copies are handed out so the tabs can iterate while the worker publishes new results.

        :param tick: The tick data bundle to update in-place.
        """
        with self._lock:
            tick.coverage_history = list(self._coverage_history)
            tick.per_test_coverage = dict(self._per_test_coverage)
            tick.covered_lines = self._covered_lines
            tick.total_lines = self._total_lines

    def wait_for_pending(self, timeout: float = 60.0) -> bool:
        """Block until all submitted work has been processed.  Intended for tests.

        :param timeout: Maximum seconds to wait.
        :return: ``True`` if the worker went idle within the timeout.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                busy = self._pending_completed is not None or self._calculating
            if not busy:
                return True
            time.sleep(0.01)
        return False

    def _ensure_worker(self) -> None:
        """Start the background calculation thread if it is not already running."""
        if self._worker is None or not self._worker.is_alive():
            self._worker = Thread(target=self._worker_loop, name="coverage_tracker", daemon=True)
            self._worker.start()

    def _worker_loop(self) -> None:
        """Daemon loop: wait for submitted work, always processing the newest pending set."""
        while True:
            self._work_available.wait()
            self._work_available.clear()
            with self._lock:
                completed = self._pending_completed
                self._pending_completed = None
                generation = self._generation
                run_start = self._current_run_start
                self._calculating = completed is not None
            if completed is None:
                continue
            try:
                self._calculate(completed, generation, run_start)
            finally:
                with self._lock:
                    self._calculating = False

    def _calculate(self, completed: set[str], generation: int, run_start: float | None) -> None:
        """Recalculate combined and per-test coverage for *completed* and publish the results.

        Results are discarded if a new run started (generation changed) while computing.
        """
        try:
            coverage_pct, covered_lines, total_lines = calculate_coverage("current", self._data_dir, write_report=False)
        except COVERAGE_READ_ERRORS as e:
            log.warning(f"coverage calculation failed: {e}")
            return

        # Recompute per-test coverage for ALL completed tests since the denominator
        # (total_lines) may have changed as new tests discover new source files.
        per_test_coverage: dict[str, float] = {}
        if total_lines > 0:
            coverage_dir = Path(self._data_dir, "coverage")
            for test_name in completed:
                safe_name = sanitize_test_name(test_name)
                cov_file = coverage_dir / f"{safe_name}.coverage"
                if cov_file.exists():
                    try:
                        cov = Coverage(cov_file)
                        cov.load()
                        data = cov.get_data()
                        executed = sum(len(data.lines(f) or []) for f in data.measured_files())
                        per_test_coverage[test_name] = executed / total_lines
                    except COVERAGE_READ_ERRORS as e:
                        log.info(f"per-test coverage for {test_name} failed: {e}")

        with self._lock:
            if generation != self._generation:
                return  # a new run started while computing — these results describe stale data
            self._covered_lines = covered_lines
            self._total_lines = total_lines
            if coverage_pct is not None:
                # Seed the first data point at the run start so the chart always has
                # at least two points — needed for a visible line/fill, especially in RESUME
                # mode when no new tests run and only one calculation happens this run.
                if not self._coverage_history and run_start is not None:
                    self._coverage_history.append((run_start, coverage_pct))
                self._coverage_history.append((time.time(), coverage_pct))
            if per_test_coverage:
                self._per_test_coverage = per_test_coverage
