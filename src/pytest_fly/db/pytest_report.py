"""
This module is responsible for writing and reading pytest "reports" to a SQLite database. This is a major portion of the "pytest-fly" pytest plugin.
"""

import json
import sqlite3
import time
from pathlib import Path
from functools import cache
from logging import getLogger
from dataclasses import dataclass
from typing import Any, Sized

from _pytest.reports import BaseReport

from ..__version__ import application_name
from .db_base import PytestFlyDBBase, get_all_table_names
from ..common import get_user_name, get_computer_name, get_guid

# "when" is a keyword in SQLite so use "pt_when"
pytest_fly_report_schema = {"id PRIMARY KEY": int, "ts": float, "uid": str, "pt_when": str, "nodeid": str, "report": json}

log = getLogger(application_name)


class PytestReportDB(PytestFlyDBBase):

    def get_db_file_name(self) -> str:
        """
        Name of DB file for pytest report.
        """
        return f"{application_name}_report.db"


def to_valid_table_name(table_name: str) -> str:
    """
    Convert a string to a valid SQLite table name.
    """
    return table_name.replace("-", "_")


@cache
def _get_process_guid() -> str:
    """
    Get a unique guid for this process by using functools.cache.
    :return: GUID string
    """
    return get_guid()


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
    with PytestReportDB(table_name, pytest_fly_report_schema) as db:
        report_json = report_to_json(report)
        statement = f"INSERT OR REPLACE INTO {table_name} (ts, uid, pt_when, nodeid, report) VALUES (?, ?, ?, ?, ?)"
        try:
            db.execute(statement, (time.time(), testrun_uid, pt_when, node_id, report_json))
        except sqlite3.OperationalError as e:
            log.error(f"{e}:{statement}")


meta_session_table_name = "_session"
meta_session_schema = {"id PRIMARY KEY": int, "ts": float, "test_name": str, "state": str}


def _write_meta_session(test_name: str, state: str):
    with PytestReportDB(meta_session_table_name, meta_session_schema) as db:
        now = time.time()
        statement = f"INSERT INTO {meta_session_table_name} (ts, test_name, state) VALUES (?, ?, ?)"
        db.execute(statement, (now, test_name, state))


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
    with PytestReportDB(meta_session_table_name, meta_session_schema) as db:
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


def get_most_recent_run_info(db_path: Path) -> dict[str, dict[str, RunInfo]]:

    # get a collection of test start and stop times

    run_infos = {}
    if (len(test_groupings := get_test_groupings())) > 0:

        most_recent_grouping = test_groupings[-1]
        start_ts = most_recent_grouping.start
        finish_ts = most_recent_grouping.finish

        table_names = get_all_table_names(db_path)
        for table_name in table_names:
            with PytestReportDB(table_name) as db:
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


def _convert_report_to_dict(report: BaseReport) -> dict[str, Any]:
    """
    Convert a pytest Report to a dict, excluding zero-length iterables, None values, and other data that's not serializable. This isn't perfect but it seems to preserve
    the data we're interested in.
    :param report: Pytest Report
    :return: a dict representation of the report
    """
    report_dict = {}
    for attr in dir(report):
        # Exclude private attributes and methods, None, and zero-length lists
        if not attr.startswith("__") and (value := getattr(report, attr)) is not None:
            has_size = isinstance(value, Sized)
            if not has_size or has_size and len(value) > 0:
                # Check if the attribute is serializable
                try:
                    json.dumps(value)
                    report_dict[attr] = value
                except TypeError:
                    # a string representation starting with "<" generally isn't a useful serialization, so ignore it
                    if not (s := str(value)).startswith("<"):
                        report_dict[attr] = s
    return report_dict


def report_to_json(report: BaseReport) -> str:
    """
    Convert Pytest Report object to a JSON string (as much as possible)
    :param report: Pytest Report
    :return: JSON string representation of the report
    """
    d = _convert_report_to_dict(report)
    # remove fields that we don't need that can have formatting issues with SQLite JSON
    removes = ["sections", "capstdout", "capstderr", "caplog", "longrepr", "longreprtext"]
    for remove in removes:
        if remove in d:
            del d[remove]
    d["fly_timestamp"] = time.time()  # pytest-fly's own timestamp
    d["username"] = get_user_name()
    d["computer_name"] = get_computer_name()
    s = json.dumps(d)
    return s
