from pathlib import Path
from dataclasses import asdict
from functools import cache
from enum import IntEnum, StrEnum

from msqlite import MSQLite
from platformdirs import user_data_dir
from balsa import get_logger
from pytest import ExitCode

from ..__version__ import application_name, author
from ..common import PytestProcessInfo, PytestProcessState, state_order


@cache
def pytest_process_info_schema() -> dict[str, type]:
    """
    Build the schema for the pytest process info database.
    """
    schema = {}
    dummy_pytest_process_info = PytestProcessInfo("", PytestProcessState.FINISHED, 0, ExitCode.OK, "", 0.0, 0.0, 0.0, 0.0)  # dummy to fill out all the fields
    for column, value in asdict(dummy_pytest_process_info).items():
        # "equivalent" SQLite types
        if isinstance(value, IntEnum):
            schema[column] = int
        elif isinstance(value, StrEnum):
            schema[column] = str
        else:
            schema[column] = type(value)
    return schema

class PytestProcessInfoDB(MSQLite):


    def __init__(self):
        db_path = Path(user_data_dir(application_name, author), f"{application_name}.db")
        table_name = application_name.replace("-", "_")  # don't use "-" in table name
        schema = pytest_process_info_schema()
        super().__init__(db_path, table_name, schema)


log = get_logger(application_name)


def save_pytest_process_info(pytest_process_info: PytestProcessInfo) -> None:
    """
    Save the pytest process info to the database.

    :param pytest_process_info: the pytest process info to save
    """

    with PytestProcessInfoDB() as db:

        schema = pytest_process_info_schema()
        columns = list(schema)
        statement = f"INSERT INTO {db.table_name} ({', '.join(columns)}) VALUES ({', '.join(['?'] * len(columns))})"
        parameters = (
            pytest_process_info.name,
            pytest_process_info.state,
            pytest_process_info.pid,
            pytest_process_info.exit_code,
            pytest_process_info.output,
            pytest_process_info.start,
            pytest_process_info.end,
            pytest_process_info.cpu_percent,
            pytest_process_info.memory_percent,
            pytest_process_info.time_stamp,
        )
        log.info(f"{statement=}, {parameters=}")
        db.execute(statement, parameters)

def delete_pytest_process_info(name: str):
    """
    Delete the pytest process info from the database.

    :param name: delete all rows with this test name
    """

    with PytestProcessInfoDB() as db:
        delete_statement = f"DELETE FROM {db.table_name} WHERE name = ?"
        db.execute(delete_statement, [name])


def query_pytest_process_info(**parameters) -> list[PytestProcessInfo]:
    """
    Query the pytest process info from the database.

    :param parameters: the parameters to query. Example: query_pytest_process_info(name="test_name")

    :return: the pytest process infos
    """

    with PytestProcessInfoDB() as db:
        query_columns = []
        query_values = []
        for column in pytest_process_info_schema():
            if column in parameters:
                query_columns.append(column)
                query_values.append(parameters[column])
        query_values = [parameters[column] for column in query_columns]
        if len(query_columns) > 0:
            query_where = " WHERE " + "AND ".join([f"{column} = ?" for column in query_columns])
        else:
            query_where = ""
        statement = f"SELECT * FROM {db.table_name}{query_where}"
        log.info(f"{statement=}, {query_values=}")
        rows = []
        for row in list(db.execute(statement, query_values)):
            pytest_process_info = PytestProcessInfo(*row)
            rows.append(pytest_process_info)

        rows.sort(key = lambda x: (state_order(x.state), x.time_stamp))

    return rows


def drop_pytest_process_info():
    with PytestProcessInfoDB() as db:
        db.execute(f"DROP TABLE {db.table_name}")
