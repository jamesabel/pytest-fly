import sqlite3
from pathlib import Path

from msqlite import MSQLite
from appdirs import user_data_dir

from ..common import rm_file
from ..__version__ import application_name, author


class PytestFlyDBBase(MSQLite):

    def __init__(self, table_name: str, schema: dict[str, type] | None = None, indexes: list[str] | None = None):
        """
        :param table_name: Name of the table.
        :param schema: Dictionary of column names and types.
        :param indexes: List of indexes to create.
        """
        self.db_path = Path(self.get_db_dir(), self.get_db_file_name())
        super().__init__(self.db_path, table_name, schema, indexes)

    def get_db_file_name(self) -> str:
        """
        Get the name of the database file.
        """
        return f"{application_name}.db"

    def get_db_dir(self) -> Path:
        """
        Get the directory where the database file is stored. Override for testing.
        """
        return user_data_dir(application_name, author)

    def delete(self):
        """
        Delete the database file. Generally not needed. Mainly for testing.
        """
        rm_file(self.db_path)


def get_all_table_names(db_path: Path) -> list[str]:
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
