import pytest
from _pytest.reports import BaseReport
from ..db import write_report, write_start, write_finish


def pytest_addoption(parser):
    parser.addoption("--fly", action="store_true")


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_logreport(report: BaseReport):
    write_report(report)


def _test_name_from_session(session) -> str:
    if hasattr(session, "startpath"):
        test_name = session.startpath.stem
    else:
        raise ValueError("session does not have startpath attribute")
    return test_name


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    test_name = _test_name_from_session(session)
    write_start(test_name)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    test_name = _test_name_from_session(session)
    write_finish(test_name)
