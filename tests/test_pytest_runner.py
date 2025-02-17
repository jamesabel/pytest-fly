from pprint import pprint
from pathlib import Path

from pytest_fly.app.controller import PytestRunner, PytestState


def test_pytest_runner():

    tests = [Path("tests", "test_font.py")]  # an "easy" test
    pytest_runner = PytestRunner(tests)  # append updates the results list
    pytest_runner.start()
    pytest_runner.wait(60 * 1000)
    status_list = pytest_runner.get_statuses()
    pprint(status_list)
    assert len(status_list) == 2
    assert status_list[0].state == PytestState.START
    assert status_list[1].state == PytestState.PASS
