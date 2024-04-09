import time

from src.pytest_fly.db import get_most_recent_start_and_finish


def test_simple_1():
    time.sleep(3)
    print("1")


def test_simple_2():
    time.sleep(6)
    print("2")


def test_start_finish():
    test_name, start, finish = get_most_recent_start_and_finish()
    print(f"{test_name=}, {start=}, {finish=}")
