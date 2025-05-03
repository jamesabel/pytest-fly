from pathlib import Path
from dataclasses import asdict
from enum import IntEnum, StrEnum

from msqlite import MSQLite
from balsa import get_logger
from pytest import ExitCode

from ...__version__ import application_name
from .interfaces import PytestProcessInfo, PytestProcessState, state_order

_db_path = Path(f".{application_name}", f"{application_name}.db")


def get_db_path() -> Path:
    """
    Get the path to the database.

    :return: the path to the database
    """
    return _db_path


def set_db_path(path: Path) -> None:
    """
    Set the path to the database.

    :param path: the path to the database
    """
    global _db_path
    _db_path = path
    _db_path.parent.mkdir(parents=True, exist_ok=True)


def _calculate_schema() -> dict[str, type]:
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


_schema = _calculate_schema()
_columns = list(_schema)


def _get_parameters(pytest_process_info: PytestProcessInfo) -> list:
    """
    Get the parameters from the pytest process info as an iterable for the database, in column order.
    """
    d = asdict(pytest_process_info)
    parameters_list = [d[c] for c in _columns]
    return parameters_list


class PytestProcessInfoDB(MSQLite):

    def __init__(self, table_name: str):
        db_path = get_db_path()
        db_path.parent.mkdir(exist_ok=True)
        super().__init__(_db_path, table_name, _schema)


class PytestProcessCurrentInfoDB(PytestProcessInfoDB):

    def __init__(self):
        table_name = "current"
        super().__init__(table_name)


log = get_logger(application_name)


# def save_pytest_process_current_info(pytest_process_info: PytestProcessInfo) -> None:
#     """
#     Save the pytest process info to the database.
#
#     :param pytest_process_info: the pytest process info to save
#     """
#
#     with PytestProcessCurrentInfoDB() as db:
#         statement = f"INSERT INTO {db.table_name} ({', '.join(_columns)}) VALUES ({', '.join(['?'] * len(_columns))})"
#         parameters = _get_parameters(pytest_process_info)
#         log.info(f"{statement=}, {parameters=}")
#         db.execute(statement, parameters)


def upsert_pytest_process_current_info(pytest_process_info: PytestProcessInfo) -> None:
    """
    Insert or update the pytest process info to the database for a given test.

    :param pytest_process_info: the pytest process info to save
    """

    with PytestProcessCurrentInfoDB() as db:
        name = pytest_process_info.name
        set_clause = ", ".join([f"{col} = ?" for col in _columns])
        update_statement = f"UPDATE {db.table_name} SET {set_clause} WHERE name = ?"
        parameters = _get_parameters(pytest_process_info)
        parameters.append(name)  # value associated with the WHERE clause
        log.info(f"{update_statement=},{name=},{parameters=}")
        cursor = db.execute(update_statement, parameters)
        if cursor.rowcount == 0:
            # no entry exists for this test, so insert it
            insert_statement = f"INSERT INTO {db.table_name} ({', '.join(_columns)}) VALUES ({', '.join(['?'] * len(_columns))})"
            insert_parameters = _get_parameters(pytest_process_info)
            log.info(f"{insert_statement=}, {insert_parameters=}")
            db.execute(insert_statement, insert_parameters)


def delete_pytest_process_current_info(name: str):
    """
    Delete the pytest process info from the database for a particular test.

    :param name: delete all rows with this test name
    """

    with PytestProcessCurrentInfoDB() as db:
        delete_statement = f"DELETE FROM {db.table_name} WHERE name = ?"
        db.execute(delete_statement, [name])


def query_pytest_process_current_info(**parameters) -> list[PytestProcessInfo]:
    """
    Query the pytest process info from the database.

    :param parameters: the parameters to query. Example: query_pytest_process_info(name="test_name")

    :return: the pytest process infos
    """

    with PytestProcessCurrentInfoDB() as db:
        query_columns = []
        query_values = []
        for column in _schema:
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

        rows.sort(key=lambda x: (state_order(x.state), x.time_stamp))  # first sort by state, then by timestamp

    return rows


def drop_pytest_process_current_info():
    with PytestProcessCurrentInfoDB() as db:
        db.execute(f"DROP TABLE {db.table_name}")
