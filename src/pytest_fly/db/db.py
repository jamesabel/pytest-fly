from pathlib import Path
from enum import IntEnum, StrEnum
import sqlite3
from dataclasses import asdict

from msqlite import MSQLite
from balsa import get_logger
from pytest import ExitCode
from typeguard import typechecked

from ..__version__ import application_name
from ..interfaces import state_order, PytestProcessInfo


log = get_logger(application_name)


class PytestProcessInfoDB(MSQLite):

    @typechecked
    def __init__(self, db_dir: Path):
        table_name = "pytest_process_info"

        self._schema = {}
        self._columns = []
        # fake to fill out all the fields since the underlying data structure is a dataclass
        dummy_pytest_process_info = PytestProcessInfo(run_guid="", name="", pid=0, exit_code=ExitCode.OK, output="", time_stamp=0.0)
        for column, value in asdict(dummy_pytest_process_info).items():
            # "equivalent" SQLite types
            if isinstance(value, IntEnum):
                self._schema[column] = int
            elif isinstance(value, StrEnum):
                self._schema[column] = str
            else:
                self._schema[column] = type(value)
            self._columns.append(column)

        db_path = Path(db_dir, "pytest_fly.sqlite")
        super().__init__(db_path, table_name, self._schema)

    @typechecked
    def write(self, pytest_process_info: PytestProcessInfo) -> None:
        """
        Write the pytest process info to the database.

        :param pytest_process_info: the pytest process info to save
        """

        insert_statement = f"INSERT INTO {self.table_name} ({', '.join(self._columns)}) VALUES ({', '.join(['?'] * len(self._columns))})"
        parameters = list(asdict(pytest_process_info).values())
        log.info(f"{insert_statement=}, {parameters=}")
        try:
            self.execute(insert_statement, parameters)
        except sqlite3.OperationalError as e:
            log.error(f'"{self.db_path}",{self.table_name=},{e}')

    def query(self, run_guid: str | None = None) -> list[PytestProcessInfo]:
        """
        Query the pytest process info from the database.

        :return: the pytest process infos
        """

        statement = f"SELECT * FROM {self.table_name}"
        if run_guid is None:
            params = None
        else:
            statement += " WHERE run_guid = ?"
            params = [run_guid]
        log.info(f'QUERY {self.table_name}: "{statement}",{params=}')
        rows = []
        for row in self.execute(statement, params):
            pytest_process_info = PytestProcessInfo(*row)
            rows.append(pytest_process_info)

        rows.sort(key=lambda x: (state_order(x.run_guid), x.time_stamp))

        return rows

    def delete(self, run_guid: str | None = None):
        if run_guid is None:
            self.execute(f"DROP TABLE {self.table_name}")
        else:
            self.execute(f"DELETE FROM {self.table_name} WHERE run_guid = ?", (run_guid,))
