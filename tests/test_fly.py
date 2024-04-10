import time

from src.pytest_fly.db import get_most_recent_start_and_finish


def test_simple_0():
    test_name, start, finish = get_most_recent_start_and_finish()
    time.sleep(0.5)
    print(f"{test_name=}, {start=}, {finish=}")


def test_simple_1():
    time.sleep(1)
    print("1")


def test_simple_2():
    time.sleep(2)
    print("2")
