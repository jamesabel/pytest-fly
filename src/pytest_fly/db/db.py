from pathlib import Path
from enum import IntEnum, StrEnum
import sqlite3
from dataclasses import asdict

from msqlite import MSQLite
from balsa import get_logger
from typeguard import typechecked

from ..__version__ import application_name
from ..interfaces import PytestProcessInfo, PyTestFlyExitCode


log = get_logger(application_name)


class PytestProcessInfoDB(MSQLite):

    @typechecked
    def __init__(self, db_dir: Path):
        table_name = "pytest_process_info"

        self._schema = {}
        self._columns = []
        # fake to fill out all the fields since the underlying data structure is a dataclass
        # use concrete non-None values for optional fields so the schema maps to the correct SQLite types
        dummy_pytest_process_info = PytestProcessInfo(run_guid="", name="", pid=0, exit_code=PyTestFlyExitCode.NONE, output="", time_stamp=0.0, cpu_percent=0.0, memory_percent=0.0)
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

        super().__init__(db_path, table_name, self._schema)

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
            pytest_process_info = PytestProcessInfo(*row)
            rows.append(pytest_process_info)

        # if no run_guid specified, filter to most recent run
        if run_guid is None:
            for row in rows:
                if run_guid is None or row.run_guid > run_guid:
                    run_guid = row.run_guid
            rows = [row for row in rows if row.run_guid == run_guid]

        return rows

    def delete(self, run_guid: str | None = None):
        if run_guid is None:
            self.execute(f"DROP TABLE {self.table_name}")
        else:
            self.execute(f"DELETE FROM {self.table_name} WHERE run_guid = ?", (run_guid,))
