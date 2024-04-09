import sqlite3
from pathlib import Path
from msqlite import MSQLite
import json
import uuid
from functools import cache
from logging import getLogger
import time
from dataclasses import dataclass
from collections import defaultdict

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
meta_session_schema = {"id PRIMARY KEY": int, "ts": float, "test_name": str, "state": str}


def _get_most_recent_row_values(db) -> tuple[int | None, str | None, float | None]:
    statement = f"SELECT * FROM {meta_session_table_name} ORDER BY ts DESC LIMIT 1"
    rows = list(db.execute(statement))
    row = rows[0] if len(rows) > 0 else None
    if row is None:
        id_state_ts = None, None, None
    else:
        id_state_ts = row[0], row[3], row[1]
    return id_state_ts


def write_start():
    db_path = get_db_path()
    with MSQLite(db_path, meta_session_table_name, meta_session_schema) as db:
        # get the most recent state
        id_value, state, ts = _get_most_recent_row_values(db)
        if state != "start":
            statement = f"INSERT OR REPLACE INTO {meta_session_table_name} (ts, state) VALUES ({time.time()}, 'start')"
            db.execute(statement)


def write_finish(test_name: str):
    db_path = get_db_path()
    with MSQLite(db_path, meta_session_table_name, meta_session_schema) as db:
        id_value, state, ts = _get_most_recent_row_values(db)
        now = time.time()
        if state == "start":
            statement = f"INSERT INTO {meta_session_table_name} (ts, test_name, state) VALUES ({now}, '{test_name}', 'finish')"
        else:
            statement = f"UPDATE {meta_session_table_name} SET ts = {now}, state = 'finish' WHERE id = {id_value}"
        db.execute(statement)


def get_most_recent_start_and_finish() -> tuple[str | None, float | None, float | None]:
    db_path = get_db_path()
    with MSQLite(db_path, meta_session_table_name, meta_session_schema) as db:
        statement = f"SELECT * FROM {meta_session_table_name} ORDER BY ts DESC LIMIT 2"
        rows = list(db.execute(statement))
        start_ts = rows[1][1]
        finish_ts = rows[0][1]
        test_name = rows[0][2]
    return test_name, start_ts, finish_ts


@dataclass
class RunInfo:
    worker_id: str | None = None
    start: float | None = None
    stop: float | None = None
    passed: bool | None = None


@dataclass(frozen=True)
class RunInfoKey:
    test_id: str
    when: str


def get_most_recent_run_info() -> dict[str, dict[str, RunInfo]]:
    test_name, start_ts, finish_ts = get_most_recent_start_and_finish()
    db_path = get_db_path()
    with MSQLite(db_path, test_name) as db:
        statement = f"SELECT * FROM {test_name} WHERE ts >= {start_ts} and ts <= {finish_ts} ORDER BY ts"
        rows = list(db.execute(statement))
    run_infos = {}
    for row in rows:
        test_data = json.loads(row[-1])
        test_id = test_data["nodeid"]
        worker_id = test_data.get("worker_id")
        when = test_data.get("when")
        start = test_data.get("start")
        stop = test_data.get("stop")
        passed = test_data.get("passed")
        if test_id in run_infos:
            run_info = run_infos[test_id]
            if start is not None:
                if run_info[when].start is None:
                    run_info[when].start = start
                else:
                    run_info[when].start = min(run_info[when].start, start)
            if stop is not None:
                if run_info[when].stop is None:
                    run_info[when].stop = stop
                else:
                    run_info[when].stop = max(run_info[when].stop, stop)
            if passed is not None:
                run_info[when].passed = passed
            if worker_id is not None:
                run_info[when].worker_id = worker_id
        else:
            run_infos[test_id] = defaultdict(RunInfo)
            run_infos[test_id][when] = RunInfo(worker_id, start, stop, passed)
    # convert defaultdict to dict
    run_infos = {test_id: dict(run_info) for test_id, run_info in run_infos.items()}
    return run_infos
