import sqlite3
from pathlib import Path
import json
import uuid
from functools import cache
from logging import getLogger
import time
from dataclasses import dataclass

from msqlite import MSQLite
from appdirs import user_data_dir

from _pytest.reports import BaseReport

from .report_converter import report_to_json
from .os import rm_file

from .__version__ import author, application_name

fly_db_file_name = f"{application_name}.db"
fly_db_path = Path(user_data_dir(application_name, author), fly_db_file_name)

log = getLogger(application_name)


def to_valid_table_name(table_name: str) -> str:
    """
    Convert a string to a valid SQLite table name.
    """
    return table_name.replace("-", "_")


def set_db_path(db_path: Path | str):
    global fly_db_path
    fly_db_path = Path(db_path)


def get_db_path() -> Path:
    fly_db_path.parent.mkdir(parents=True, exist_ok=True)
    return fly_db_path


@cache
def _get_process_guid() -> str:
    """
    Get a unique guid for this process by using functools.cache.
    :return: GUID string
    """
    return str(uuid.uuid4())


# "when" is a keyword in SQLite so use "pt_when"
fly_schema = {"id PRIMARY KEY": int, "ts": float, "uid": str, "pt_when": str, "nodeid": str, "report": json}


class PytestFlyDB(MSQLite):

    def __init__(self, table_name: str, schema: dict[str, type] | None = None, retry_limit: int | None = None):
        db_path = get_db_path()
        log.info(f"{db_path=}")
        super().__init__(db_path, table_name, schema, retry_limit=retry_limit)

    def delete(self):
        """
        Delete the database file. Generally not needed. Mainly for testing.
        """
        rm_file(self.db_path)


def _get_table_name_from_report(report: BaseReport) -> str:
    """
    Get the table name from the report file path
    """
    table_name = Path(report.fspath).parts[0]
    table_name = to_valid_table_name(table_name)

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
    table_name = _get_table_name_from_report(report)
    pt_when = report.when
    node_id = report.nodeid
    setattr(report, "is_xdist", is_xdist)  # signify if we're running pytest-xdist or not
    with PytestFlyDB(table_name, fly_schema) as db:
        report_json = report_to_json(report)
        statement = f"INSERT OR REPLACE INTO {table_name} (ts, uid, pt_when, nodeid, report) VALUES ({time.time()}, '{testrun_uid}', '{pt_when}', '{node_id}', '{report_json}')"
        try:
            db.execute(statement)
        except sqlite3.OperationalError as e:
            log.error(f"{e}:{statement}")


meta_session_table_name = "_session"
meta_session_schema = {"id PRIMARY KEY": int, "ts": float, "test_name": str, "state": str}


def _write_meta_session(test_name: str, state: str):
    with PytestFlyDB(meta_session_table_name, meta_session_schema) as db:
        now = time.time()
        statement = f"INSERT INTO {meta_session_table_name} (ts, test_name, state) VALUES ({now}, '{test_name}', '{state}')"
        db.execute(statement)


def write_start(test_name: str | None):
    _write_meta_session(test_name, "start")


def write_finish(test_name: str):
    _write_meta_session(test_name, "finish")


@dataclass(frozen=True, order=True)
class TestGrouping:
    start: float
    finish: float
    test_name: str


def get_test_groupings() -> list[TestGrouping]:
    """
    Get a list of test groupings from the database.
    """
    time_stamp_column = 1
    test_name_column = 2
    phase_column = 3
    phase = None
    test_name = None
    test_grouping = None
    test_groupings = []
    with PytestFlyDB(meta_session_table_name, meta_session_schema) as db:
        statement = f"SELECT * FROM {meta_session_table_name} ORDER BY ts"
        result = db.execute(statement)
        rows = list(result)
        earliest_start = None
        for row in rows:
            phase = row[phase_column]
            test_name = row[test_name_column]
            if phase == "start":
                if test_grouping is not None:
                    # "pending" grouping
                    test_groupings.append(test_grouping)
                    test_grouping = None
                time_stamp = row[time_stamp_column]
                if earliest_start is None or time_stamp < earliest_start:
                    earliest_start = time_stamp
            elif phase == "finish":
                finish_ts = row[time_stamp_column]
                test_grouping = TestGrouping(earliest_start, finish_ts, test_name)
            else:
                raise ValueError(f"Unknown phase: {row[phase_column]}")

    if test_grouping is None:
        if phase == "start":
            # Grouping without a finish. Use current time.
            test_grouping = TestGrouping(earliest_start, time.time(), test_name)
            test_groupings.append(test_grouping)
    else:
        test_groupings.append(test_grouping)

    test_groupings.sort(key=lambda x: x.start)

    return test_groupings


@dataclass
class RunInfo:
    worker_id: str | None = None
    start: float | None = None
    stop: float | None = None
    passed: bool | None = None


def _get_all_table_names(db_path: Path) -> list[str]:
    """
    Get all table names in the SQLite database.
    :param db_path: Path to the SQLite database file.
    :return: List of table names.
    """
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        table_names = [row[0] for row in cursor.fetchall() if not row[0].startswith("_")]
    return table_names


def get_most_recent_run_info() -> dict[str, dict[str, RunInfo]]:

    # get a collection of test start and stop times

    run_infos = {}
    if (len(test_groupings := get_test_groupings())) > 0:

        most_recent_grouping = test_groupings[-1]
        start_ts = most_recent_grouping.start
        finish_ts = most_recent_grouping.finish

        db_path = get_db_path()
        table_names = _get_all_table_names(db_path)
        for table_name in table_names:
            with PytestFlyDB(table_name) as db:
                statement = f"SELECT * FROM {table_name} WHERE ts BETWEEN {start_ts} AND {finish_ts} ORDER BY ts"
                try:
                    rows = list(db.execute(statement))
                except sqlite3.OperationalError as e:
                    log.warning(f"{e}:{statement}")
                    rows = []
                for row in rows:
                    test_data = json.loads(row[-1])
                    test_id = test_data.get("nodeid")
                    worker_id = test_data.get("worker_id")
                    when = test_data.get("when")
                    start = test_data.get("start")
                    stop = test_data.get("stop")
                    passed = test_data.get("passed")
                    if test_id not in run_infos:
                        run_infos[test_id] = {}
                    if when not in run_infos[test_id]:
                        run_infos[test_id][when] = {}
                    run_infos[test_id][when] = RunInfo(worker_id, start, stop, passed)

    return run_infos
