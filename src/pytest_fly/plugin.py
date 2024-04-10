import pytest
from _pytest.reports import BaseReport
from src.pytest_fly.db import write_report, write_start, write_finish


def pytest_addoption(parser):
    write_start()
    parser.addoption("--fly", action="store_true")


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_logreport(report: BaseReport):
    write_report(report)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    table_name = session.startpath.name
    write_finish(table_name)
