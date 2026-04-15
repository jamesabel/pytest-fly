import time

from pytest_fly.db import PytestProcessInfoDB
from pytest_fly.guid import generate_uuid
from pytest_fly.interfaces import PyTestFlyExitCode, PytestProcessInfo

from .paths import get_temp_dir

pid = 1234
output = "test"


def test_pytest_process_info_db_query():

    test_name = "test_pytest_process_info_db_query_one"
    db_dir = get_temp_dir(test_name)

    guid = generate_uuid()

    with PytestProcessInfoDB(db_dir) as db:
        db.write(PytestProcessInfo(run_guid=guid, name=test_name, pid=pid, exit_code=PyTestFlyExitCode.NONE, output=output, time_stamp=time.time()))
        db.write(PytestProcessInfo(run_guid=guid, name=test_name, pid=pid, exit_code=PyTestFlyExitCode.OK, output=output, time_stamp=time.time()))

        rows = db.query(guid)
        assert len(rows) == 2

        row = rows[0]
        assert row.name == test_name
        assert row.pid == pid
        assert row.exit_code == PyTestFlyExitCode.NONE

        assert rows[1].exit_code == PyTestFlyExitCode.OK


def test_pytest_process_info_db_query_none():

    test_name = "test_pytest_process_info_db_query_none"
    db_dir = get_temp_dir(test_name)

    guid = generate_uuid()
    with PytestProcessInfoDB(db_dir) as db:
        db.write(PytestProcessInfo(run_guid=guid, name=test_name, pid=pid, exit_code=PyTestFlyExitCode.NONE, output=output, time_stamp=time.time()))
        rows = db.query("I am not a valid guid")
        assert len(rows) == 0


def test_pytest_process_info_db_delete_by_guid():
    """Delete records for one guid and verify the other guid's records remain."""

    test_name = "test_pytest_process_info_db_delete_by_guid"
    db_dir = get_temp_dir(test_name)

    guid_a = generate_uuid()
    guid_b = generate_uuid()

    with PytestProcessInfoDB(db_dir) as db:
        db.write(PytestProcessInfo(run_guid=guid_a, name="test_a", pid=pid, exit_code=PyTestFlyExitCode.OK, output=output, time_stamp=time.time()))
        db.write(PytestProcessInfo(run_guid=guid_b, name="test_b", pid=pid, exit_code=PyTestFlyExitCode.OK, output=output, time_stamp=time.time()))

        db.delete(guid_a)

        rows_a = db.query(guid_a)
        assert len(rows_a) == 0

        rows_b = db.query(guid_b)
        assert len(rows_b) == 1
        assert rows_b[0].name == "test_b"


def test_pytest_process_info_db_query_most_recent():
    """query(None) should return only the most recent run's records."""

    test_name = "test_pytest_process_info_db_query_most_recent"
    db_dir = get_temp_dir(test_name)

    guid_old = "aaa-old"
    guid_new = "zzz-new"

    with PytestProcessInfoDB(db_dir) as db:
        db.write(PytestProcessInfo(run_guid=guid_old, name="test_old", pid=pid, exit_code=PyTestFlyExitCode.OK, output=output, time_stamp=time.time()))
        db.write(PytestProcessInfo(run_guid=guid_new, name="test_new", pid=pid, exit_code=PyTestFlyExitCode.OK, output=output, time_stamp=time.time()))

        rows = db.query()  # None = most recent
        assert len(rows) == 1
        assert rows[0].run_guid == guid_new


def test_query_last_pass():
    """query_last_pass returns data from the most recent passing run, even if a later run failed."""

    db_dir = get_temp_dir("test_query_last_pass")
    now = time.time()
    guid_a = "aaa-run-a"
    guid_b = "bbb-run-b"

    with PytestProcessInfoDB(db_dir) as db:
        # Run A: test_x passes (queued, started, completed OK)
        db.write(PytestProcessInfo(run_guid=guid_a, name="test_x", pid=None, exit_code=PyTestFlyExitCode.NONE, output=None, time_stamp=now))
        db.write(PytestProcessInfo(run_guid=guid_a, name="test_x", pid=100, exit_code=PyTestFlyExitCode.NONE, output=None, time_stamp=now + 1))
        db.write(PytestProcessInfo(run_guid=guid_a, name="test_x", pid=100, exit_code=PyTestFlyExitCode.OK, output="passed", time_stamp=now + 6))

        # Run B: test_x fails
        db.write(PytestProcessInfo(run_guid=guid_b, name="test_x", pid=None, exit_code=PyTestFlyExitCode.NONE, output=None, time_stamp=now + 100))
        db.write(PytestProcessInfo(run_guid=guid_b, name="test_x", pid=200, exit_code=PyTestFlyExitCode.NONE, output=None, time_stamp=now + 101))
        db.write(PytestProcessInfo(run_guid=guid_b, name="test_x", pid=200, exit_code=PyTestFlyExitCode.TESTS_FAILED, output="failed", time_stamp=now + 108))

        result = db.query_last_pass()
        assert "test_x" in result
        start_ts, duration = result["test_x"]
        assert start_ts == now + 1  # first record with pid set in run A
        assert abs(duration - 5.0) < 0.01  # 6 - 1 = 5 seconds


def test_query_last_pass_never_passed():
    """query_last_pass returns empty dict for a test that has never passed."""

    db_dir = get_temp_dir("test_query_last_pass_never_passed")
    now = time.time()
    guid = "aaa-run"

    with PytestProcessInfoDB(db_dir) as db:
        db.write(PytestProcessInfo(run_guid=guid, name="test_y", pid=None, exit_code=PyTestFlyExitCode.NONE, output=None, time_stamp=now))
        db.write(PytestProcessInfo(run_guid=guid, name="test_y", pid=100, exit_code=PyTestFlyExitCode.NONE, output=None, time_stamp=now + 1))
        db.write(PytestProcessInfo(run_guid=guid, name="test_y", pid=100, exit_code=PyTestFlyExitCode.TESTS_FAILED, output="fail", time_stamp=now + 3))

        result = db.query_last_pass()
        assert "test_y" not in result


def test_query_last_pass_multiple_passes():
    """query_last_pass returns the most recent passing run when a test passed in multiple runs."""

    db_dir = get_temp_dir("test_query_last_pass_multiple_passes")
    now = time.time()
    guid_a = "aaa-run-a"
    guid_b = "bbb-run-b"

    with PytestProcessInfoDB(db_dir) as db:
        # Run A: test_x passes with duration 5s
        db.write(PytestProcessInfo(run_guid=guid_a, name="test_x", pid=100, exit_code=PyTestFlyExitCode.NONE, output=None, time_stamp=now))
        db.write(PytestProcessInfo(run_guid=guid_a, name="test_x", pid=100, exit_code=PyTestFlyExitCode.OK, output="passed", time_stamp=now + 5))

        # Run B: test_x passes with duration 3s
        db.write(PytestProcessInfo(run_guid=guid_b, name="test_x", pid=200, exit_code=PyTestFlyExitCode.NONE, output=None, time_stamp=now + 100))
        db.write(PytestProcessInfo(run_guid=guid_b, name="test_x", pid=200, exit_code=PyTestFlyExitCode.OK, output="passed", time_stamp=now + 103))

        result = db.query_last_pass()
        assert "test_x" in result
        start_ts, duration = result["test_x"]
        assert start_ts == now + 100  # from run B (most recent)
        assert abs(duration - 3.0) < 0.01
