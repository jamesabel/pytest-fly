import time
import shutil
from pathlib import Path

from src.pytest_fly.db import get_most_recent_start_and_finish, get_db_path

from tests.orchestrator import wait_for_current_test, done


def test_simple_0():

    # db_file_path = get_db_path()
    # snapshot_db_file_name = db_file_path.name.replace(".db", "_snapshot_0.db")
    # shutil.copy2(db_file_path, Path("temp", snapshot_db_file_name))

    test_number = 0
    time.sleep(5)
    # wait_for_current_test(test_number)
    # done(test_number)


def test_simple_1():
    time.sleep(10)
    test_number = 1
    # wait_for_current_test(test_number)
    # done(test_number)


def test_simple_2():
    time.sleep(15)
    test_number = 2
    # wait_for_current_test(test_number)
    # done(test_number)
    # test_name, start, finish = get_most_recent_start_and_finish()
    # assert test_name is not None and len(test_name) > 0
