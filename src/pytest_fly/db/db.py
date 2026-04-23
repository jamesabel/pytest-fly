"""
SQLite persistence layer for :class:`PytestProcessInfo` records.

Uses `msqlite <https://pypi.org/project/msqlite/>`_ for thread-safe access
and derives the table schema automatically from the dataclass fields.
"""

import sqlite3
from dataclasses import asdict
from enum import IntEnum, StrEnum
from pathlib import Path

from msqlite import MSQLite
from typeguard import typechecked

from ..__version__ import application_name
from ..interfaces import PyTestFlyExitCode, PytestProcessInfo
from ..logger import get_logger

log = get_logger()


class PytestProcessInfoDB(MSQLite):
    """
    Thread-safe SQLite store for :class:`PytestProcessInfo` records.

    The table schema is derived automatically from the dataclass fields.
    If a schema change is detected (columns differ from what is on disk),
    the table is dropped and recreated — test results are ephemeral so data
    loss is acceptable.
    """

    # Paths whose schema and journal-mode have already been validated this
    # process.  The GUI reopens this class on every refresh tick and the
    # schema/pragma work only needs to run once.
    _initialized_paths: set[Path] = set()

    @typechecked
    def __init__(self, db_dir: Path):
        table_name = "pytest_process_info"

        self._schema = {}
        self._columns = []
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
        )
        for column, value in asdict(dummy_pytest_process_info).items():
            # "equivalent" SQLite types
            if isinstance(value, IntEnum):
                self._schema[column] = int
            elif isinstance(value, StrEnum):
                self._schema[column] = str
            else:
                self._schema[column] = type(value)
            self._columns.append(column)

        db_path = Path(db_dir, f"{application_name}.db")

        if db_path not in PytestProcessInfoDB._initialized_paths:
            # Schema migration: if the table exists with a different set of columns, drop it so
            # MSQLite recreates it with the current schema.  Test results are ephemeral, so data loss is acceptable.
            # Note: sqlite3 context manager only handles transactions, not closing — call close() explicitly
            # to release the Windows file lock before MSQLite opens its own connection below.
            if db_path.exists():
                _conn = sqlite3.connect(db_path)
                try:
                    existing_columns = {row[1] for row in _conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
                finally:
                    _conn.close()
                if existing_columns and existing_columns != set(self._columns):
                    log.info(f"Schema change detected for {table_name!r} – dropping table to recreate with new schema")
                    _conn = sqlite3.connect(db_path)
                    try:
                        _conn.execute(f"DROP TABLE IF EXISTS {table_name}")
                        _conn.commit()
                    finally:
                        _conn.close()

            # WAL lets GUI readers proceed concurrently with test-process writers instead of
            # serializing through BEGIN EXCLUSIVE — the main source of GUI-read stalls while a run
            # is in progress.  WAL mode is a persistent per-file property, but re-issuing the pragma
            # on a WAL database is a no-op, so the one-shot guard is sufficient.
            _conn = sqlite3.connect(db_path)
            try:
                _conn.execute("PRAGMA journal_mode=WAL")
                _conn.commit()
            finally:
                _conn.close()

            PytestProcessInfoDB._initialized_paths.add(db_path)

        super().__init__(db_path, table_name, self._schema, indexes=["run_guid", "exit_code"])

    @typechecked
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

        :param run_guid: the run GUID to filter on, or None to get the most recent.
        :return: the pytest process infos
        """

        statement = f"SELECT * FROM {self.table_name}"
        if run_guid is None:
            params = None
        else:
            statement += " WHERE run_guid = ?"
            params = [run_guid]
        log.debug(f'QUERY {self.table_name}: "{statement}",{params=}')
        rows = []
        for row in self.execute(statement, params):
            row_dict = dict(zip(self._columns, row))
            pytest_process_info = PytestProcessInfo(**row_dict)
            rows.append(pytest_process_info)

        # if no run_guid specified, filter to most recent run
        if run_guid is None:
            for row in rows:
                if run_guid is None or row.run_guid > run_guid:
                    run_guid = row.run_guid
            rows = [row for row in rows if row.run_guid == run_guid]

        return rows

    def query_last_pass(self) -> dict[str, tuple[float, float]]:
        """
        For each test name, find the most recent run where the test passed.

        Searches across all ``run_guid`` values to locate the latest passing
        result (``exit_code == OK``) for every test.

        :return: Dictionary mapping test name to ``(start_timestamp, duration_seconds)``.
        """

        ok_val = int(PyTestFlyExitCode.OK)
        statement = f"""
            SELECT p.name, s.start_ts, p.time_stamp AS end_ts
            FROM (
                SELECT name, MAX(run_guid) AS run_guid
                FROM {self.table_name}
                WHERE exit_code = ?
                GROUP BY name
            ) latest
            JOIN {self.table_name} p
                ON p.name = latest.name
                AND p.run_guid = latest.run_guid
                AND p.exit_code = ?
            JOIN (
                SELECT name, run_guid, MIN(time_stamp) AS start_ts
                FROM {self.table_name}
                WHERE pid IS NOT NULL
                GROUP BY name, run_guid
            ) s
                ON s.name = latest.name
                AND s.run_guid = latest.run_guid
        """
        result = {}
        try:
            for row in self.execute(statement, [ok_val, ok_val]):
                name, start_ts, end_ts = row[0], row[1], row[2]
                if start_ts is not None and end_ts is not None:
                    result[name] = (start_ts, end_ts - start_ts)
        except sqlite3.OperationalError as e:
            log.debug(f"query_last_pass failed (table may not exist yet): {e}")
        return result

    def query_ever_run_names(self) -> set[str]:
        """Return the set of test node_ids that have ever been run, across all runs and PUT versions.

        Filters out queued-but-never-started placeholder rows (``pid IS NULL``) — these are
        written by :class:`PytestRunner` before a test actually spawns and by ``_drain_queue``
        when a run is stopped, so they do not count as "ever run."

        :return: Set of test node_ids.  Empty if the table does not yet exist.
        """
        statement = f"SELECT DISTINCT name FROM {self.table_name} WHERE pid IS NOT NULL"
        result: set[str] = set()
        try:
            for row in self.execute(statement):
                if row[0] is not None:
                    result.add(row[0])
        except sqlite3.OperationalError as e:
            log.debug(f"query_ever_run_names failed (table may not exist yet): {e}")
        return result

    def delete(self, run_guid: str | None = None):
        """
        Delete records.  If *run_guid* is ``None`` the entire table is dropped;
        otherwise only records matching the GUID are removed.
        """
        if run_guid is None:
            self.execute(f"DROP TABLE {self.table_name}")
        else:
            self.execute(f"DELETE FROM {self.table_name} WHERE run_guid = ?", (run_guid,))
