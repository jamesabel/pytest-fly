import time

from pytest import ExitCode

from pytest_fly import PytestProcessInfo, PytestProcessState, save_pytest_process_info, query_pytest_process_info, drop_pytest_process_info

pytest_process_info = PytestProcessInfo(
    name="test",
    state=PytestProcessState.FINISHED,
    pid=1234,
    exit_code=ExitCode.OK,
    output="test",
    start=time.time(),
    end=time.time(),
    cpu_percent=0.0,
    memory_percent=0.0,
    time_stamp=time.time(),
)


# def test_pytest_process_info_db(init_pytest_process_info):
#
#     save_pytest_process_info(pytest_process_info)
#     rows = query_pytest_process_info()
#     assert len(rows) > 0
#     row = rows[0]
#     assert row == pytest_process_info


def test_pytest_process_info_db_query_one(init_pytest_process_info):

    save_pytest_process_info(pytest_process_info)
    rows = query_pytest_process_info(name="test")
    assert len(rows) > 0
    row = rows[0]
    assert row.name == pytest_process_info.name
    assert row.state == pytest_process_info.state
    assert row.pid == pytest_process_info.pid
    assert row.exit_code == pytest_process_info.exit_code


def test_pytest_process_info_db_query_none(init_pytest_process_info):

    save_pytest_process_info(pytest_process_info)
    rows = query_pytest_process_info(name="I do not exist")
    assert len(rows) == 0
