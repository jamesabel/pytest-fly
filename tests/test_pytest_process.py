from tempfile import TemporaryDirectory
from pathlib import Path

from pytest import ExitCode
from pytest_fly.pytest_runner.pytest_process import PytestProcess
from pytest_fly.guid import generate_uuid
from pytest_fly.db import PytestProcessInfoDB


def test_pytest_process():
    with TemporaryDirectory() as data_dir:
        run_uuid = generate_uuid()
        pytest_process = PytestProcess(run_uuid, Path("tests/test_no_operation.py"), Path(data_dir), 3.0)
        pytest_process.start()
        pytest_process.join()

        with PytestProcessInfoDB(Path(data_dir)) as db:
            results = db.query(run_uuid)
            assert len(results) >= 2  # at least start and end entries

        assert len(results) >= 2
        assert results[-1].exit_code == ExitCode.OK
        execution_time = results[-1].time_stamp - results[0].time_stamp
        print(f"{execution_time=}")
        assert execution_time >= 0.0  # 1.4768257141113281 has been observed
