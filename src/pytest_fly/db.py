import sqlite3
from pathlib import Path
from msqlite import MSQLite
import json
import uuid
from functools import cache
from logging import getLogger
import time

from appdirs import user_data_dir

from _pytest.reports import BaseReport

from src.pytest_fly.report_converter import report_to_json

from .__version__ import author, application_name

g_table_name = ""  # will get set at initialization
fly_db_path = Path(user_data_dir(application_name, author), f"{application_name}.db")

log = getLogger(application_name)


def set_db_path(db_path: Path | str):
    global fly_db_path
    fly_db_path = Path(db_path)


def get_db_path() -> Path:
    fly_db_path.parent.mkdir(parents=True, exist_ok=True)
    return Path(fly_db_path)


def set_table_name(table_name: str):
    global g_table_name
    g_table_name = table_name


def get_table_name() -> str:
    return g_table_name


@cache
def _get_process_guid() -> str:
    """
    Get a unique guid for this process by using functools.cache.
    :return: GUID string
    """
    return str(uuid.uuid4())


# "when" is a keyword in SQLite so use "pt_when"
fly_schema = {"id PRIMARY KEY": int, "ts": float, "uid": str, "pt_when": str, "nodeid": str, "report": json}


def get_table_name_from_report(report: BaseReport) -> str:
    """
    Get the table name from the report file path
    """
    table_name = Path(report.fspath).parts[0]
    set_table_name(table_name)
    return table_name


def write_report(report: BaseReport):
    """
    Write a pytest report to the database
    :param report: pytest report
    """
    try:
        testrun_uid = report.testrun_uid  # pytest-xdist
        is_xdist = True
    except AttributeError:
        testrun_uid = _get_process_guid()  # single threaded
        is_xdist = False
    table_name = get_table_name_from_report(report)
    pt_when = report.when
    node_id = report.nodeid
    setattr(report, "is_xdist", is_xdist)  # signify if we're running pytest-xdist or not
    db_path = get_db_path()
    with MSQLite(db_path, table_name, fly_schema) as db:
        report_json = report_to_json(report)
        statement = f"INSERT OR REPLACE INTO {table_name} (ts, uid, pt_when, nodeid, report) VALUES ({time.time()}, '{testrun_uid}', '{pt_when}', '{node_id}', '{report_json}')"
        try:
            db.execute(statement)
        except sqlite3.OperationalError as e:
            log.error(f"{e}:{statement}")


def read_json_objects_by_uid(uid: str, table_name: str = get_table_name()):
    with MSQLite(get_db_path(), table_name) as db:
        statement = f"SELECT * FROM {table_name} WHERE uid = {uid}"
        rows = db.execute(statement)
    return rows


def get_all_test_run_ids(table_name: str = get_table_name()) -> set[str]:
    with MSQLite(get_db_path(), table_name) as db:
        test_run_ids = set()
        rows = db.execute(f"SELECT * FROM {table_name}")
        for row in rows:
            run_id = row[2]
            test_run_ids.add(run_id)
    return test_run_ids


meta_session_table_name = "_session"
meta_session_schema = {"id PRIMARY KEY": int, "ts": float, "state": str}


def _get_most_recent_state_and_time(db) -> tuple[int | None, str | None, float | None]:
    statement = f"SELECT * FROM {meta_session_table_name} ORDER BY ts DESC LIMIT 1"
    rows = list(db.execute(statement))
    row = rows[0] if len(rows) > 0 else None
    if row is None:
        state_ts = None, None, None
    else:
        state_ts = row[0], row[2], row[1]
    return state_ts

def write_start():
    db_path = get_db_path()
    with MSQLite(db_path, meta_session_table_name, meta_session_schema) as db:
        # get the most recent state
        id_value, state, ts = _get_most_recent_state_and_time(db)
        if state != "start":
            statement = f"INSERT OR REPLACE INTO {meta_session_table_name} (ts, state) VALUES ({time.time()}, 'start')"
            db.execute(statement)


def write_finish():
    db_path = get_db_path()
    with MSQLite(db_path, meta_session_table_name, meta_session_schema) as db:
        id_value, state, ts = _get_most_recent_state_and_time(db)
        now = time.time()
        if state == "start":
            statement = f"INSERT INTO {meta_session_table_name} (ts, state) VALUES ({now}, 'finish')"
        else:
            statement = f"UPDATE {meta_session_table_name} SET ts = {now}, state = 'finish' WHERE id = {id_value}"
        db.execute(statement)
