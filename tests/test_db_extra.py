"""Additional coverage for :class:`pytest_fly.db.PytestProcessInfoDB`."""

import sqlite3
import time

from pytest_fly.__version__ import application_name
from pytest_fly.db import PytestProcessInfoDB
from pytest_fly.guid import generate_uuid
from pytest_fly.interfaces import PyTestFlyExitCode, PytestProcessInfo

from .paths import get_temp_dir


def _info(guid, name, pid, exit_code, ts):
    return PytestProcessInfo(run_guid=guid, name=name, pid=pid, exit_code=exit_code, output=None, time_stamp=ts)


def test_query_ever_run_names_excludes_unstarted():
    """query_ever_run_names returns started tests (pid set) and excludes queued-only ones."""
    db_dir = get_temp_dir("test_ever_run_names")
    guid = generate_uuid()
    now = time.time()
    with PytestProcessInfoDB(db_dir) as db:
        db.write(_info(guid, "test_started", 100, PyTestFlyExitCode.OK, now))
        db.write(_info(guid, "test_queued_only", None, PyTestFlyExitCode.NONE, now))
        names = db.query_ever_run_names()
    assert "test_started" in names
    assert "test_queued_only" not in names


def test_delete_all_drops_table():
    """delete() with no guid drops the table; subsequent queries degrade gracefully to empty."""
    db_dir = get_temp_dir("test_delete_all")
    guid = generate_uuid()
    now = time.time()
    with PytestProcessInfoDB(db_dir) as db:
        db.write(_info(guid, "test_a", 1, PyTestFlyExitCode.OK, now))
        db.delete()  # None -> DROP TABLE
        # The table is gone; query_ever_run_names catches the OperationalError and returns empty.
        assert db.query_ever_run_names() == set()
        assert db.query_last_pass() == {}


def test_schema_change_drops_and_recreates(tmp_path):
    """An on-disk table with a stale schema is dropped and recreated on open."""
    db_path = tmp_path / f"{application_name}.db"
    # Seed a table whose columns don't match the current dataclass-derived schema.
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE pytest_process_info (obsolete_column TEXT)")
        conn.commit()
    finally:
        conn.close()

    # Ensure the one-shot init guard doesn't skip the schema check for this path.
    PytestProcessInfoDB._initialized_paths.discard(db_path)

    guid = generate_uuid()
    with PytestProcessInfoDB(tmp_path) as db:
        db.write(_info(guid, "test_a", 1, PyTestFlyExitCode.OK, time.time()))
        rows = db.query(guid)
    assert len(rows) == 1
    assert rows[0].name == "test_a"
