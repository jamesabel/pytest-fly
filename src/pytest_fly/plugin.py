import pytest
from _pytest.reports import BaseReport
from .db import write_report, write_start, write_finish


def pytest_addoption(parser):
    write_start()
    parser.addoption("--fly", action="store_true")


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_logreport(report: BaseReport):
    write_report(report)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    item = session.items[0]
    test_name = item.nodeid.split('/')[0]
    write_finish(test_name)
