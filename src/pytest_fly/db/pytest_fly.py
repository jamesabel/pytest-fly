from typeguard import typechecked

from .db_base import PytestFlyDBBase
from ..common.interfaces import PytestResult, PytestStatus

from ..__version__ import application_name

schema = {"id PRIMARY KEY": int, "ts": float, "run_uid": str, "max_processes": int, "test_name": str, "status": str, "result": str, "out": str}
indexes = ["run_uid", "test_name"]
table_name = "status"


class PytestFlyDB(PytestFlyDBBase):

    def __init__(self):
        # id - unique id for the record (not part of the pytest run itself)
        # ts - timestamp
        # run_uid - unique id for the pytest run
        # max_processes - maximum number of processes
        # test_name - name of the particular test
        # state - state of the test (queued, running, finished)
        # result - result of the test (passed, failed, skipped, error)
        # out - stdout/stderr output
        super().__init__(table_name, schema, indexes)

    def get_db_file_name(self) -> str:
        return f"{application_name}_status.db"


@typechecked()
def write_test_status(run_uid: str, max_processes: int, test_name: str, status: PytestStatus, result: PytestResult | None):
    """
    Write a pytest test status to the database
    :param run_uid: unique id for the pytest run
    :param max_processes: maximum number of processes
    :param test_name: name of the particular test
    :param status: status of the test
    :param result: result of the test
    """
    with PytestFlyDB() as db:
        statement = "INSERT INTO status (ts, run_uid, max_processes, test_name, status, result, out) VALUES (?, ?, ?, ?, ?, ?, ?)"
        parameters = [status.time_stamp, run_uid, max_processes, test_name, status.state]
        if result is None:
            parameters.extend([None, None])
        else:
            parameters.extend([result.exit_code, result.output])
        db.execute(statement, parameters)
