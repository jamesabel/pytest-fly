"""Out-of-process coverage aggregation.

:func:`pytest_fly.pytest_runner.coverage.calculate_coverage` combines every per-test
``.coverage`` file and runs ``coverage.report()`` over the whole program under test — a large
parse-and-teardown that has crashed the interpreter natively (access violation inside
``python.dll``) while running on a thread inside the GUI process, taking the orchestrator and
the run down with it.

Nothing about that work needs to be in-process: it reads files and returns numbers.  So it
runs in a short-lived spawn child, like :class:`ProcessMonitor` and :class:`GetTests`.  A child
that dies or hangs is a logged warning and the last good values stand; the run continues.

The same child also counts per-test executed lines (for the Coverage tab's per-test view and
for coverage-efficiency ordering) when asked, so that no :class:`coverage.Coverage` object is
ever constructed in the GUI process at all.
"""

import time
from dataclasses import dataclass, field
from multiprocessing import Process, Queue
from pathlib import Path
from queue import Empty

from ..faults import enable_faulthandler
from ..logger import EVENT_EXTRA, configure_child_logger, get_logger
from .coverage import calculate_coverage, per_test_executed_lines

log = get_logger()


@dataclass(frozen=True)
class CoverageResult:
    """What one aggregation pass produced.

    ``per_test_executed_lines`` and ``union_executed_lines`` are only populated when the
    caller supplied ``per_test_names``; they describe those tests only.
    """

    coverage: float | None  # overall coverage 0.0-1.0, or None when there is no data yet
    covered_statements: int
    total_statements: int
    per_test_executed_lines: dict[str, int] = field(default_factory=dict)  # test node_id -> executed line count
    union_executed_lines: int = 0  # size of the union of executed lines across the requested tests

    @property
    def totals(self) -> tuple[float | None, int, int]:
        """The ``(coverage, covered, total)`` triple, as :func:`calculate_coverage` returns it."""
        return self.coverage, self.covered_statements, self.total_statements

    def per_test_fractions(self, denominator: int | None = None) -> dict[str, float]:
        """Per-test executed lines as fractions of *denominator*.

        :param denominator: line count to divide by; ``None`` uses ``union_executed_lines``
            (the coverage-efficiency ordering convention).  The Coverage tab passes
            ``total_statements`` instead.
        :return: empty when the denominator is zero.
        """
        if denominator is None:
            denominator = self.union_executed_lines
        if denominator <= 0:
            return {}
        return {name: executed / denominator for name, executed in self.per_test_executed_lines.items()}


class CoverageAggregator(Process):
    """Spawn child that runs :func:`calculate_coverage` once and reports a :class:`CoverageResult` on a queue."""

    def __init__(self, test_identifier: str, coverage_parent_directory: Path, write_report: bool, per_test_names: list[str] | None = None) -> None:
        super().__init__(name="coverage_aggregator", daemon=True)
        self._test_identifier = test_identifier
        self._coverage_parent_directory = coverage_parent_directory
        self._write_report = write_report
        self._per_test_names = list(per_test_names) if per_test_names else []
        self._result_queue: Queue = Queue()

    def run(self) -> None:
        configure_child_logger("coverage_aggregator.log")
        enable_faulthandler()  # reads PYTEST_FLY_FAULTHANDLER from the inherited environment
        coverage, covered, total = calculate_coverage(self._test_identifier, self._coverage_parent_directory, self._write_report)
        per_test: dict[str, int] = {}
        union = 0
        if self._per_test_names:
            per_test, union = per_test_executed_lines(self._coverage_parent_directory, self._per_test_names)
        self._result_queue.put(CoverageResult(coverage, covered, total, per_test, union))

    def result(self) -> CoverageResult | None:
        """The child's result, or ``None`` if it produced none (crashed, killed, or still running)."""
        try:
            return self._result_queue.get_nowait()
        except Empty:
            return None


def aggregate_coverage(test_identifier: str, coverage_parent_directory: Path, write_report: bool, timeout: float, per_test_names: list[str] | None = None) -> CoverageResult | None:
    """Run :func:`calculate_coverage` in a child process and wait for it.

    :param timeout: seconds before the child is terminated as hung.
    :param per_test_names: tests whose executed-line counts should also be returned (see
        :attr:`CoverageResult.per_test_executed_lines`); ``None`` skips that pass.
    :return: the coverage result, or ``None`` when the child crashed, was killed, or timed out —
             never raises for those; the caller keeps its last good values.
    """
    start = time.monotonic()
    child = CoverageAggregator(test_identifier, coverage_parent_directory, write_report, per_test_names)
    child.start()
    child.join(timeout)
    if child.is_alive():
        child.terminate()
        child.join()
        log.warning(f"coverage aggregation timed out after {timeout:.0f}s and was terminated (pid {child.pid})", extra=EVENT_EXTRA)
        return None
    result = child.result()
    if child.exitcode != 0 or result is None:
        # A negative exit code is a signal (native crash); see faulthandler-<pid>.log for the stack.
        log.warning(f"coverage aggregation process {child.pid} exited with code {child.exitcode} without a result — keeping previous coverage values", extra=EVENT_EXTRA)
        return None
    log.debug(f"coverage aggregation took {time.monotonic() - start:.1f}s (pid {child.pid})")
    return result
