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

from .report_converter import report_to_json

from .__version__ import author, application_name

fly_db_file_name = f"{application_name}.db"
fly_db_path = Path(user_data_dir(application_name, author), fly_db_file_name)

log = getLogger(application_name)


def set_db_path(db_path: Path | str):
    global fly_db_path
    fly_db_path = Path(db_path)


def get_db_path() -> Path:
    fly_db_path.parent.mkdir(parents=True, exist_ok=True)
    return Path(fly_db_path)


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


meta_session_table_name = "_session"
meta_session_schema = {"id PRIMARY KEY": int, "ts": float, "test_name": str, "state": str}


def _write_meta_session(test_name: str, state: str):
    db_path = get_db_path()
    with MSQLite(db_path, meta_session_table_name, meta_session_schema, retry_limit=10) as db:
        now = time.time()

        # update meta_session table
        statement = f"SELECT * FROM {meta_session_table_name} WHERE state = '{state}'"
        rows = list(db.execute(statement))
        if len(rows) > 0:
            statement = f"UPDATE {meta_session_table_name} SET ts = {now} WHERE state = '{state}'"
        else:
            statement = f"INSERT OR REPLACE INTO {meta_session_table_name} (ts, test_name, state) VALUES ({time.time()}, '{test_name}', '{state}')"
        db.execute(statement)

        # clear out any prior run data
        if state == "start":
            statement = f"DELETE FROM {meta_session_table_name} WHERE state = 'finish'"
            db.execute(statement)
            statement = f"DROP TABLE IF EXISTS {test_name}"
            db.execute(statement)
            statement = f"CREATE TABLE {test_name} (id INTEGER PRIMARY KEY, ts FLOAT, uid TEXT, pt_when TEXT, nodeid TEXT, report TEXT)"
            db.execute(statement)


def write_start(test_name: str | None):
    _write_meta_session(test_name, "start")


def write_finish(test_name: str):
    _write_meta_session(test_name, "finish")


def get_most_recent_start_and_finish() -> tuple[str | None, float | None, float | None]:
    start_ts = None
    finish_ts = None
    time_stamp_column = 1
    test_name_column = 2
    phase_column = 3
    db_path = get_db_path()
    with MSQLite(db_path, meta_session_table_name, meta_session_schema) as db:
        statement = f"SELECT * FROM {meta_session_table_name} ORDER BY ts DESC LIMIT 2"
        result = db.execute(statement)
        rows = list(result)
        for row in rows:
            if row[phase_column] == "start":
                start_ts = row[time_stamp_column]
                test_name = row[test_name_column]
            elif row[phase_column] == "finish":
                finish_ts = row[time_stamp_column]
                test_name = row[test_name_column]
            else:
                raise ValueError(f"Unknown phase: {row[phase_column]}")

    return test_name, start_ts, finish_ts


@dataclass
class RunInfo:
    worker_id: str | None = None
    start: float | None = None
    stop: float | None = None
    passed: bool | None = None


def get_most_recent_run_info() -> dict[str, dict[str, RunInfo]]:
    test_name, start_ts, finish_ts = get_most_recent_start_and_finish()

    db_path = get_db_path()
    with MSQLite(db_path, test_name) as db:
        if finish_ts is None:
            statement = f"SELECT * FROM {test_name} WHERE ts >= {start_ts} ORDER BY ts"
        else:
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
