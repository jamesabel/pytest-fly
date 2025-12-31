import time

from pytest import ExitCode

from pytest_fly.db import PytestProcessInfoDB
from pytest_fly.interfaces import PytestProcessInfo
from pytest_fly.guid import generate_uuid

from .paths import get_temp_dir

pid = 1234
output = "test"


def test_pytest_process_info_db_query():

    test_name = "test_pytest_process_info_db_query_one"
    db_dir = get_temp_dir(test_name)

    guid = generate_uuid()

    with PytestProcessInfoDB(db_dir) as db:
        db.write(PytestProcessInfo(run_guid=guid, name=test_name, pid=pid, exit_code=None, output=output, time_stamp=time.time()))
        db.write(PytestProcessInfo(run_guid=guid, name=test_name, pid=pid, exit_code=ExitCode.OK, output=output, time_stamp=time.time()))

        rows = db.query(guid)
        assert len(rows) == 2

        row = rows[0]
        assert row.name == test_name
        assert row.pid == pid
        assert row.exit_code is None

        assert rows[1].exit_code == ExitCode.OK


def test_pytest_process_info_db_query_none():

    test_name = "test_pytest_process_info_db_query_none"
    db_dir = get_temp_dir(test_name)

    guid = generate_uuid()
    with PytestProcessInfoDB(db_dir) as db:
        db.write(PytestProcessInfo(run_guid=guid, name=test_name, pid=pid, exit_code=None, output=output, time_stamp=time.time()))
        rows = db.query("I am not a valid guid")
        assert len(rows) == 0
