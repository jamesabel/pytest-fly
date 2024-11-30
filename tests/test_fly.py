import time
import json
import random

import requests

from src.pytest_fly.db import get_most_recent_start_and_finish

from tests.orchestrator import completed_key, current_test_key, get_http_url


def get_current_test() -> int:
    response = requests.get(get_http_url())
    response_dict = json.loads(response.text)
    current_test = int(response_dict[current_test_key])
    return current_test


def wait_for_current_test(expected_current_test: int):
    while (current_test := get_current_test()) != expected_current_test:
        print(f"Waiting for {expected_current_test=}, {current_test=}")
        time.sleep(random.random())
    print(f"Done waiting for {expected_current_test=}, {current_test=}")


def done(test_number: int):
    requests.post(get_http_url(), json={completed_key: test_number})


def test_simple_0():
    time.sleep(5)
    test_number = 0
    test_name, start, finish = get_most_recent_start_and_finish()
    print(f"{test_name=}, {start=}, {finish=}")
    wait_for_current_test(test_number)
    done(test_number)


def test_simple_1():
    time.sleep(10)
    test_number = 1
    wait_for_current_test(test_number)
    done(test_number)


def test_simple_2():
    time.sleep(15)
    test_number = 2
    wait_for_current_test(test_number)
    done(test_number)
