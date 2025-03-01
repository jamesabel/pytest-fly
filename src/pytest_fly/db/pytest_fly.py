from typeguard import typechecked

from .db_base import PytestFlyDBBase
from ..common.classes import PytestResult, PytestStatus

from ..__version__ import application_name

# id - unique id for the record (not part of the pytest run itself)
# ts - timestamp
# run_uid - unique id for the pytest run
# test_name - name of the particular test
# state - state of the test (queued, running, finished)
# result - result of the test (passed, failed, skipped, error)
# out - stdout/stderr output
pytest_fly_status_schema = {"id PRIMARY KEY": int, "ts": float, "run_uid": str, "test_name": str, "status": str, "result": str, "out": str}


class PytestFlyDB(PytestFlyDBBase):

    def get_db_file_name(self) -> str:
        return f"{application_name}_status.db"


@typechecked()
def write_test_status(run_uid: str, test_name: str, status: PytestStatus, result: PytestResult | None):
    """
    Write a pytest test status to the database
    :param run_uid: unique id for the pytest run
    :param test_name: name of the particular test
    :param status: status of the test
    :param result: result of the test
    """
    with PytestFlyDB("status", pytest_fly_status_schema) as db:
        if result is None:
            statement = f"INSERT INTO status (ts, run_uid, test_name, status, result, out) VALUES ({status.time_stamp}, '{run_uid}', '{test_name}', '{status.state}', NULL, NULL)"
        else:
            statement = f"INSERT INTO status (ts, run_uid, test_name, status, result, out) VALUES ({status.time_stamp}, '{run_uid}', '{test_name}', '{status.state}', '{result.exit_code}', '{result.output}')"
        db.execute(statement)
