"""Run-history summarization — grouping DB records by run into per-run summaries.

Covers pass/fail statistics, failed-test lists, run timing, completion detection,
version-label selection, and most-recent-first ordering.
"""

from pytest_fly.interfaces import PyTestFlyExitCode, PytestProcessInfo
from pytest_fly.run_history import build_run_history


def _record(run_guid: str, name: str, exit_code: PyTestFlyExitCode, time_stamp: float, pid: int | None = 1234, put_version: str | None = "") -> PytestProcessInfo:
    return PytestProcessInfo(run_guid=run_guid, name=name, pid=pid, exit_code=exit_code, output=None, time_stamp=time_stamp, put_version=put_version)


def test_build_run_history_empty():
    assert build_run_history([]) == []


def test_build_run_history_counts_and_failed_tests():
    infos = [
        _record("run-1", "tests/test_a.py", PyTestFlyExitCode.NONE, 100.0),
        _record("run-1", "tests/test_a.py", PyTestFlyExitCode.OK, 110.0),
        _record("run-1", "tests/test_b.py", PyTestFlyExitCode.TESTS_FAILED, 112.0),
        _record("run-1", "tests/test_c.py", PyTestFlyExitCode.USAGE_ERROR, 114.0),
        _record("run-1", "tests/test_d.py", PyTestFlyExitCode.STOPPED, 116.0, pid=None),
    ]
    (summary,) = build_run_history(infos)
    assert summary.run_guid == "run-1"
    assert summary.n_pass == 1
    assert summary.n_fail == 2  # any non-OK pytest exit code is a failure
    assert summary.n_other == 1  # the stopped test
    assert summary.n_total == 4
    assert summary.failed_tests == ("tests/test_b.py", "tests/test_c.py")
    assert summary.start_ts == 100.0
    assert summary.end_ts == 116.0
    assert summary.duration == 16.0
    assert summary.is_complete is True


def test_build_run_history_latest_record_wins():
    """A test's state comes from its most recent record — a failure then a passing rerun counts as a pass."""
    infos = [
        _record("run-1", "tests/test_a.py", PyTestFlyExitCode.TESTS_FAILED, 100.0),
        _record("run-1", "tests/test_a.py", PyTestFlyExitCode.OK, 110.0),
    ]
    (summary,) = build_run_history(infos)
    assert summary.n_pass == 1
    assert summary.n_fail == 0
    assert summary.failed_tests == ()


def test_build_run_history_in_progress_run():
    """A run with queued or running tests is not complete."""
    infos = [
        _record("run-1", "tests/test_a.py", PyTestFlyExitCode.OK, 100.0),
        _record("run-1", "tests/test_b.py", PyTestFlyExitCode.NONE, 101.0),  # running (has a pid)
        _record("run-1", "tests/test_c.py", PyTestFlyExitCode.NONE, 102.0, pid=None),  # queued
    ]
    (summary,) = build_run_history(infos)
    assert summary.is_complete is False
    assert summary.n_pass == 1
    assert summary.n_other == 2


def test_build_run_history_most_recent_first():
    """Runs are ordered by run GUID descending (UUIDv7 GUIDs are time-ordered)."""
    infos = [
        _record("run-1", "tests/test_a.py", PyTestFlyExitCode.OK, 100.0),
        _record("run-3", "tests/test_a.py", PyTestFlyExitCode.OK, 300.0),
        _record("run-2", "tests/test_a.py", PyTestFlyExitCode.OK, 200.0),
    ]
    assert [summary.run_guid for summary in build_run_history(infos)] == ["run-3", "run-2", "run-1"]


def test_build_run_history_put_version_from_newest_labeled_record():
    """Status records carry an empty version label; the newest non-empty label is used."""
    infos = [
        _record("run-1", "tests/test_a.py", PyTestFlyExitCode.NONE, 100.0, put_version="put 1.0"),
        _record("run-1", "tests/test_a.py", PyTestFlyExitCode.OK, 110.0, put_version="put 1.1"),
        _record("run-1", "tests/test_b.py", PyTestFlyExitCode.STOPPED, 120.0, pid=None, put_version=""),
    ]
    (summary,) = build_run_history(infos)
    assert summary.put_version == "put 1.1"


def test_build_run_history_no_version_label():
    infos = [_record("run-1", "tests/test_a.py", PyTestFlyExitCode.OK, 100.0, put_version=None)]
    (summary,) = build_run_history(infos)
    assert summary.put_version == ""
