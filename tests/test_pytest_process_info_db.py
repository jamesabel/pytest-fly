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
