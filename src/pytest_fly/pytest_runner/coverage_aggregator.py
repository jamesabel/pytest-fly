"""Out-of-process coverage aggregation.

:func:`pytest_fly.pytest_runner.coverage.calculate_coverage` combines every per-test
``.coverage`` file and runs ``coverage.report()`` over the whole program under test — a large
parse-and-teardown that has crashed the interpreter natively (access violation inside
``python.dll``) while running on a thread inside the GUI process, taking the orchestrator and
the run down with it.

Nothing about that work needs to be in-process: it reads files and returns three numbers.  So it
runs in a short-lived spawn child, like :class:`ProcessMonitor` and :class:`GetTests`.  A child
that dies or hangs is a logged warning and the last good values stand; the run continues.
"""

import time
from multiprocessing import Process, Queue
from pathlib import Path
from queue import Empty

from ..faults import enable_faulthandler
from ..logger import EVENT_EXTRA, configure_child_logger, get_logger
from .coverage import calculate_coverage

log = get_logger()

CoverageResult = tuple[float | None, int, int]  # (coverage 0.0-1.0 or None, covered statements, total statements)


class CoverageAggregator(Process):
    """Spawn child that runs :func:`calculate_coverage` once and reports the result on a queue."""

    def __init__(self, test_identifier: str, coverage_parent_directory: Path, write_report: bool) -> None:
        super().__init__(name="coverage_aggregator", daemon=True)
        self._test_identifier = test_identifier
        self._coverage_parent_directory = coverage_parent_directory
        self._write_report = write_report
        self._result_queue: Queue = Queue()

    def run(self) -> None:
        configure_child_logger("coverage_aggregator.log")
        enable_faulthandler()  # reads PYTEST_FLY_FAULTHANDLER from the inherited environment
        result = calculate_coverage(self._test_identifier, self._coverage_parent_directory, self._write_report)
        self._result_queue.put(result)

    def result(self) -> CoverageResult | None:
        """The child's result, or ``None`` if it produced none (crashed, killed, or still running)."""
        try:
            return self._result_queue.get_nowait()
        except Empty:
            return None


def aggregate_coverage(test_identifier: str, coverage_parent_directory: Path, write_report: bool, timeout: float) -> CoverageResult | None:
    """Run :func:`calculate_coverage` in a child process and wait for it.

    :param timeout: seconds before the child is terminated as hung.
    :return: the coverage result, or ``None`` when the child crashed, was killed, or timed out —
             never raises for those; the caller keeps its last good values.
    """
    start = time.monotonic()
    child = CoverageAggregator(test_identifier, coverage_parent_directory, write_report)
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
