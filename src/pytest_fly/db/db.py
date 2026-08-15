"""
SQLite persistence layer for :class:`PytestProcessInfo` records.

Two access classes share the same table and query logic:

- :class:`PytestProcessInfoDB` — read/write, built on
  `msqlite <https://pypi.org/project/msqlite/>`_, whose context manager holds the
  file's EXCLUSIVE write lock for the duration of the ``with`` block.  Use it for
  writes (and reads that must be atomic with a write in the same transaction).
- :class:`PytestProcessInfoReader` — read-only, for the GUI thread and monitor
  threads.  It opens a plain connection and only issues SELECTs, so under WAL
  journal mode it neither blocks nor is blocked by concurrent test-process
  writers.  Routing GUI reads through the msqlite class instead would contend
  for the exclusive lock several times per refresh tick — the main source of
  intermittent multi-second GUI freezes during a run.
"""

import sqlite3
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict
from enum import IntEnum, StrEnum
from pathlib import Path

from msqlite import MSQLite
from typeguard import typechecked

from ..__version__ import application_name
from ..interfaces import PyTestFlyExitCode, PytestProcessInfo, is_terminal_exit_code, status_record
from ..logger import get_logger

log = get_logger()

_TABLE_NAME = "pytest_process_info"

# SQLite's default variable limit is 999; keep IN-clause chunks comfortably below it.
_IN_CLAUSE_CHUNK = 500


def _derive_schema() -> tuple[dict[str, type], list[str]]:
    """Derive the SQLite schema and ordered column list from the :class:`PytestProcessInfo` dataclass."""
    schema: dict[str, type] = {}
    columns: list[str] = []
    # fake to fill out all the fields since the underlying data structure is a dataclass
    # use concrete non-None values for optional fields so the schema maps to the correct SQLite types
    dummy_pytest_process_info = PytestProcessInfo(
        run_guid="",
        name="",
        pid=0,
        exit_code=PyTestFlyExitCode.NONE,
        output="",
        time_stamp=0.0,
        cpu_percent=0.0,
        memory_percent=0.0,
        put_version="",
        put_fingerprint="",
        commit_bytes=0,
    )
    for column, value in asdict(dummy_pytest_process_info).items():
        # "equivalent" SQLite types
        if isinstance(value, IntEnum):
            schema[column] = int
        elif isinstance(value, StrEnum):
            schema[column] = str
        else:
            schema[column] = type(value)
        columns.append(column)
    return schema, columns


# The shared query implementations take an executor callable so both access classes reuse
# them: the writer passes MSQLite.execute (runs inside its exclusive transaction and
# auto-creates the table), the reader passes its own fail-open SELECT runner.
_ExecuteFn = Callable[[str, Sequence | None], Iterable]


def _query_records(execute_fn: _ExecuteFn, columns: list[str], run_guid: str | None, include_output: bool) -> list[PytestProcessInfo]:
    """Query records, optionally omitting the (potentially huge) ``output`` column.

    ``run_guid=None`` returns only the most recent run, selected as the
    lexicographically greatest GUID — valid because run GUIDs are UUIDv7
    (time-ordered; see :func:`pytest_fly.guid.generate_uuid`).
    """
    selected_columns = columns if include_output else [c for c in columns if c != "output"]
    statement = f"SELECT {', '.join(selected_columns)} FROM {_TABLE_NAME}"
    if run_guid is None:
        params = None
    else:
        statement += " WHERE run_guid = ?"
        params = [run_guid]
    rows = []
    for row in execute_fn(statement, params):
        row_dict = dict(zip(selected_columns, row))
        if not include_output:
            row_dict["output"] = None
        rows.append(PytestProcessInfo(**row_dict))

    # if no run_guid specified, filter to most recent run
    if run_guid is None:
        for row in rows:
            if run_guid is None or row.run_guid > run_guid:
                run_guid = row.run_guid
        rows = [row for row in rows if row.run_guid == run_guid]

    return rows


def _query_last_pass(execute_fn: _ExecuteFn) -> dict[str, tuple[float, float]]:
    """For each test name, find the most recent run where the test passed.

    Searches across all ``run_guid`` values to locate the latest passing
    result (``exit_code == OK``) for every test.

    :return: Dictionary mapping test name to ``(start_timestamp, duration_seconds)``.
    """
    ok_val = int(PyTestFlyExitCode.OK)
    statement = f"""
        SELECT p.name, s.start_ts, p.time_stamp AS end_ts
        FROM (
            SELECT name, MAX(run_guid) AS run_guid
            FROM {_TABLE_NAME}
            WHERE exit_code = ?
            GROUP BY name
        ) latest
        JOIN {_TABLE_NAME} p
            ON p.name = latest.name
            AND p.run_guid = latest.run_guid
            AND p.exit_code = ?
        JOIN (
            SELECT name, run_guid, MIN(time_stamp) AS start_ts
            FROM {_TABLE_NAME}
            WHERE pid IS NOT NULL
            GROUP BY name, run_guid
        ) s
            ON s.name = latest.name
            AND s.run_guid = latest.run_guid
    """
    result = {}
    try:
        for row in execute_fn(statement, [ok_val, ok_val]):
            name, start_ts, end_ts = row[0], row[1], row[2]
            if start_ts is not None and end_ts is not None:
                result[name] = (start_ts, end_ts - start_ts)
    except sqlite3.OperationalError as e:
        log.debug(f"query_last_pass failed (table may not exist yet): {e}")
    return result


def _query_ever_run_names(execute_fn: _ExecuteFn) -> set[str]:
    """Return the set of test node_ids that have ever been run, across all runs and PUT versions.

    Filters out queued-but-never-started placeholder rows (``pid IS NULL``) — these are
    written by :class:`PytestRunner` before a test actually spawns and at soft-stop
    finalization when a run is stopped, so they do not count as "ever run."
    """
    statement = f"SELECT DISTINCT name FROM {_TABLE_NAME} WHERE pid IS NOT NULL"
    result: set[str] = set()
    try:
        for row in execute_fn(statement, None):
            if row[0] is not None:
                result.add(row[0])
    except sqlite3.OperationalError as e:
        log.debug(f"query_ever_run_names failed (table may not exist yet): {e}")
    return result


def _db_path(db_dir: Path) -> Path:
    return Path(db_dir, f"{application_name}.db")


class PytestProcessInfoDB(MSQLite):
    """
    Thread-safe SQLite store for :class:`PytestProcessInfo` records.

    The table schema is derived automatically from the dataclass fields.
    If a schema change is detected (columns differ from what is on disk),
    the table is dropped and recreated — test results are ephemeral so data
    loss is acceptable.

    Note: entering this context manager acquires the database's EXCLUSIVE write
    lock (msqlite) for the whole ``with`` block.  Pure reads on latency-sensitive
    threads (the GUI) should use :class:`PytestProcessInfoReader` instead.
    """

    # Paths whose schema and journal-mode have already been validated this
    # process.  The GUI reopens this class on every refresh tick and the
    # schema/pragma work only needs to run once.
    _initialized_paths: set[Path] = set()

    @typechecked()
    def __init__(self, db_dir: Path):
        self._schema, self._columns = _derive_schema()

        db_path = _db_path(db_dir)

        if db_path not in PytestProcessInfoDB._initialized_paths:
            # Schema migration: if the table exists with a different set of columns, drop it so
            # MSQLite recreates it with the current schema.  Test results are ephemeral, so data loss is acceptable.
            # Note: sqlite3 context manager only handles transactions, not closing — call close() explicitly
            # to release the Windows file lock before MSQLite opens its own connection below.
            if db_path.exists():
                _conn = sqlite3.connect(db_path)
                try:
                    existing_columns = {row[1] for row in _conn.execute(f"PRAGMA table_info({_TABLE_NAME})").fetchall()}
                finally:
                    _conn.close()
                if existing_columns and existing_columns != set(self._columns):
                    log.info(f"Schema change detected for {_TABLE_NAME!r} – dropping table to recreate with new schema")
                    _conn = sqlite3.connect(db_path)
                    try:
                        _conn.execute(f"DROP TABLE IF EXISTS {_TABLE_NAME}")
                        _conn.commit()
                    finally:
                        _conn.close()

            # WAL is what makes PytestProcessInfoReader's lock-free reads possible: readers see a
            # consistent snapshot and neither block nor are blocked by the (msqlite-serialized)
            # writers.  WAL mode is a persistent per-file property, but re-issuing the pragma
            # on a WAL database is a no-op, so the one-shot guard is sufficient.
            _conn = sqlite3.connect(db_path)
            try:
                _conn.execute("PRAGMA journal_mode=WAL")
                _conn.commit()
            finally:
                _conn.close()

            PytestProcessInfoDB._initialized_paths.add(db_path)

        super().__init__(db_path, _TABLE_NAME, self._schema, indexes=["run_guid", "exit_code"])

    @typechecked()
    def write(self, pytest_process_info: PytestProcessInfo) -> None:
        """
        Write the pytest process info to the database.

        :param pytest_process_info: the pytest process info to save
        """

        insert_statement = f"INSERT INTO {self.table_name} ({', '.join(self._columns)}) VALUES ({', '.join(['?'] * len(self._columns))})"
        parameters = list(asdict(pytest_process_info).values())
        log.debug(f"{insert_statement=}, {parameters=}")
        try:
            self.execute(insert_statement, parameters)
        except sqlite3.OperationalError as e:
            log.error(f'"{self.db_path}",{self.table_name=},{e}')

    def query(self, run_guid: str | None = None) -> list[PytestProcessInfo]:
        """
        Query the pytest process info from the database.

        ``run_guid=None`` returns only the most recent run (see :func:`_query_records`).

        :param run_guid: the run GUID to filter on, or None to get the most recent.
        :return: the pytest process infos
        """
        return _query_records(self.execute, self._columns, run_guid, include_output=True)

    @typechecked()
    def mark_test_terminated_if_stale(self, run_guid: str | None, test_name: str) -> bool:
        """Write a TERMINATED record for *test_name* if its latest record is non-terminal.

        Used to clear a stale "Running" row — a test whose process died (or was lost, e.g.
        across an app restart) without ever writing a terminal record.  Guarded so a test
        that actually finished is never clobbered: if the latest record already carries a
        terminal exit code, nothing is written.

        :param run_guid: The run to search, or ``None`` for the most recent run (matching
            what the GUI displays when no run is active).
        :param test_name: The test node_id to mark.
        :return: ``True`` if a TERMINATED record was written, ``False`` otherwise.
        """
        infos = [info for info in self.query(run_guid) if info.name == test_name]
        if not infos:
            return False
        latest = max(infos, key=lambda info: info.time_stamp)
        if is_terminal_exit_code(latest.exit_code):
            return False  # already terminal — a real result must not be overwritten
        self.write(status_record(latest.run_guid, test_name, PyTestFlyExitCode.TERMINATED, latest.put_version, latest.put_fingerprint))
        return True

    def query_last_pass(self) -> dict[str, tuple[float, float]]:
        """For each test name, ``(start_timestamp, duration_seconds)`` of its most recent passing run."""
        return _query_last_pass(self.execute)

    def query_ever_run_names(self) -> set[str]:
        """Return the set of test node_ids that have ever been run, across all runs and PUT versions."""
        return _query_ever_run_names(self.execute)

    def delete(self, run_guid: str | None = None):
        """
        Delete records.  If *run_guid* is ``None`` the entire table is dropped;
        otherwise only records matching the GUID are removed.
        """
        if run_guid is None:
            self.execute(f"DROP TABLE {self.table_name}")
        else:
            self.execute(f"DELETE FROM {self.table_name} WHERE run_guid = ?", (run_guid,))


class PytestProcessInfoReader:
    """Read-only query access that never takes the database's write lock.

    Opens a plain connection and only issues SELECTs; under WAL these read a
    consistent snapshot without blocking (or being blocked by) writers.  Every
    method fails open: a missing database file, an unopenable connection, or a
    not-yet-created table all yield empty results.
    """

    @typechecked()
    def __init__(self, db_dir: Path):
        self.db_path = _db_path(db_dir)
        _unused_schema, self._columns = _derive_schema()
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> "PytestProcessInfoReader":
        if self.db_path.exists():
            try:
                self._conn = sqlite3.connect(self.db_path, timeout=2.0)
            except sqlite3.OperationalError as e:
                log.debug(f'could not open "{self.db_path}" for reading: {e}')
                self._conn = None
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _execute(self, statement: str, parameters: Sequence | None = None) -> list[tuple]:
        """Run a SELECT and return all rows; empty on a missing file/table (fail-open)."""
        if self._conn is None:
            return []
        try:
            return self._conn.execute(statement, parameters or []).fetchall()
        except sqlite3.OperationalError as e:
            log.debug(f"read-only query failed (table may not exist yet): {e}")
            return []

    def query(self, run_guid: str | None = None, include_output: bool = False) -> list[PytestProcessInfo]:
        """Query records; by default the ``output`` column is omitted (``output=None`` on the records).

        Completed tests' output blobs dominate the row size; per-tick GUI queries leave them
        out and fetch them once per completed test via :meth:`query_outputs`.

        :param run_guid: the run GUID to filter on, or None to get the most recent run.
        :param include_output: when ``True``, include the full ``output`` column.
        :return: the pytest process infos
        """
        return _query_records(self._execute, self._columns, run_guid, include_output)

    def query_outputs(self, run_guid: str, names: Iterable[str]) -> dict[str, tuple[float, str]]:
        """Fetch the latest stored output for specific tests of one run.

        :param run_guid: The run to search.
        :param names: Test node_ids to fetch outputs for.
        :return: Mapping of test name to ``(record_time_stamp, output)`` for its most recent
            record carrying an output.  Tests with no stored output are omitted.
        """
        result: dict[str, tuple[float, str]] = {}
        names = list(names)
        for chunk_start in range(0, len(names), _IN_CLAUSE_CHUNK):
            chunk = names[chunk_start : chunk_start + _IN_CLAUSE_CHUNK]
            placeholders = ", ".join(["?"] * len(chunk))
            statement = f"SELECT name, time_stamp, output FROM {_TABLE_NAME} WHERE run_guid = ? AND output IS NOT NULL AND name IN ({placeholders})"
            for name, time_stamp, output in self._execute(statement, [run_guid, *chunk]):
                prior = result.get(name)
                if prior is None or time_stamp >= prior[0]:
                    result[name] = (time_stamp, output)
        return result

    def query_last_pass(self) -> dict[str, tuple[float, float]]:
        """For each test name, ``(start_timestamp, duration_seconds)`` of its most recent passing run."""
        return _query_last_pass(self._execute)

    def query_ever_run_names(self) -> set[str]:
        """Return the set of test node_ids that have ever been run, across all runs and PUT versions."""
        return _query_ever_run_names(self._execute)
