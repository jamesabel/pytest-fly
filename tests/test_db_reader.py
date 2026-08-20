"""PytestProcessInfoReader — lock-free read-only DB access used by the GUI thread.

Verifies parity with the msqlite-backed writer's queries, the default omission of the
output column (with on-demand fetch via query_outputs), and fail-open behavior when the
database does not exist yet.
"""

import time

from pytest_fly.db import PytestProcessInfoDB, PytestProcessInfoReader
from pytest_fly.interfaces import PyTestFlyExitCode, PytestProcessInfo

from .paths import get_temp_dir


def _record(run_guid: str, name: str, exit_code: PyTestFlyExitCode, output: str | None, time_stamp: float, pid: int | None = 1234) -> PytestProcessInfo:
    return PytestProcessInfo(run_guid=run_guid, name=name, pid=pid, exit_code=exit_code, output=output, time_stamp=time_stamp)


def test_reader_missing_db_fails_open():
    data_dir = get_temp_dir("reader_missing_db")
    with PytestProcessInfoReader(data_dir) as reader:
        assert reader.query() == []
        assert reader.query("some-guid") == []
        assert reader.query_outputs("some-guid", ["tests/test_a.py"]) == {}
        assert reader.query_last_pass() == {}
        assert reader.query_ever_run_names() == set()
        assert reader.query_recent_runs(5) == []
        assert reader.query_change_token() == (0, 0)


def test_reader_query_omits_output_by_default():
    data_dir = get_temp_dir("reader_omits_output")
    now = time.time()
    with PytestProcessInfoDB(data_dir) as db:
        db.write(_record("run-1", "tests/test_a.py", PyTestFlyExitCode.OK, "captured output A", now))

    with PytestProcessInfoReader(data_dir) as reader:
        infos = reader.query("run-1")
        assert len(infos) == 1
        assert infos[0].name == "tests/test_a.py"
        assert infos[0].exit_code == PyTestFlyExitCode.OK
        assert infos[0].output is None  # omitted by default

        infos_full = reader.query("run-1", include_output=True)
        assert infos_full[0].output == "captured output A"


def test_reader_most_recent_run_selection():
    """run_guid=None must select only the lexicographically greatest run GUID, like the writer."""
    data_dir = get_temp_dir("reader_most_recent")
    now = time.time()
    with PytestProcessInfoDB(data_dir) as db:
        db.write(_record("run-1", "tests/test_a.py", PyTestFlyExitCode.OK, "old", now - 100))
        db.write(_record("run-2", "tests/test_b.py", PyTestFlyExitCode.OK, "new", now))

    with PytestProcessInfoReader(data_dir) as reader:
        names = {info.name for info in reader.query()}
    with PytestProcessInfoDB(data_dir) as db:
        writer_names = {info.name for info in db.query()}
    assert names == writer_names == {"tests/test_b.py"}


def test_reader_query_outputs_latest_per_name():
    data_dir = get_temp_dir("reader_query_outputs")
    now = time.time()
    with PytestProcessInfoDB(data_dir) as db:
        db.write(_record("run-1", "tests/test_a.py", PyTestFlyExitCode.NONE, None, now - 10))  # running record, no output
        db.write(_record("run-1", "tests/test_a.py", PyTestFlyExitCode.TESTS_FAILED, "first output", now - 5))
        db.write(_record("run-1", "tests/test_a.py", PyTestFlyExitCode.OK, "final output", now))
        db.write(_record("run-1", "tests/test_b.py", PyTestFlyExitCode.STOPPED, None, now, pid=None))  # never produced output
        db.write(_record("run-2", "tests/test_a.py", PyTestFlyExitCode.OK, "other run", now + 5))

    with PytestProcessInfoReader(data_dir) as reader:
        outputs = reader.query_outputs("run-1", ["tests/test_a.py", "tests/test_b.py", "tests/test_missing.py"])
    assert set(outputs.keys()) == {"tests/test_a.py"}
    time_stamp, output = outputs["tests/test_a.py"]
    assert output == "final output"
    assert time_stamp > 0.0


def test_reader_matches_writer_for_last_pass_and_ever_run():
    data_dir = get_temp_dir("reader_parity")
    now = time.time()
    with PytestProcessInfoDB(data_dir) as db:
        db.write(_record("run-1", "tests/test_a.py", PyTestFlyExitCode.NONE, None, now - 20))
        db.write(_record("run-1", "tests/test_a.py", PyTestFlyExitCode.OK, "out", now - 10))
        db.write(_record("run-1", "tests/test_b.py", PyTestFlyExitCode.NONE, None, now - 20, pid=None))  # queued only — never ran

    with PytestProcessInfoDB(data_dir) as db:
        writer_last_pass = db.query_last_pass()
        writer_ever_run = db.query_ever_run_names()
    with PytestProcessInfoReader(data_dir) as reader:
        assert reader.query_last_pass() == writer_last_pass
        assert reader.query_ever_run_names() == writer_ever_run
    assert "tests/test_a.py" in writer_last_pass
    assert writer_ever_run == {"tests/test_a.py"}


def test_reader_query_recent_runs_limit_and_ordering():
    """Only the N most recent runs are returned (UUIDv7-ordered GUIDs), output omitted."""
    data_dir = get_temp_dir("reader_recent_runs")
    now = time.time()
    with PytestProcessInfoDB(data_dir) as db:
        for run_index in range(3):
            db.write(_record(f"run-{run_index}", "tests/test_a.py", PyTestFlyExitCode.OK, f"output {run_index}", now + run_index))

    with PytestProcessInfoReader(data_dir) as reader:
        infos = reader.query_recent_runs(2)
        assert {info.run_guid for info in infos} == {"run-1", "run-2"}
        assert all(info.output is None for info in infos)
        assert len(reader.query_recent_runs(10)) == 3  # limit larger than the run count is fine


def test_reader_change_token_tracks_writes():
    data_dir = get_temp_dir("reader_change_token")
    now = time.time()
    with PytestProcessInfoDB(data_dir) as db:
        db.write(_record("run-1", "tests/test_a.py", PyTestFlyExitCode.OK, "out", now))
    with PytestProcessInfoReader(data_dir) as reader:
        token_before = reader.query_change_token()
        assert reader.query_change_token() == token_before  # stable when nothing was written

    with PytestProcessInfoDB(data_dir) as db:
        db.write(_record("run-1", "tests/test_b.py", PyTestFlyExitCode.OK, "out", now + 1))
    with PytestProcessInfoReader(data_dir) as reader:
        assert reader.query_change_token() != token_before


def test_reader_does_not_create_db_file():
    """Opening the reader must not create an empty database file as a side effect."""
    data_dir = get_temp_dir("reader_no_create")
    with PytestProcessInfoReader(data_dir) as reader:
        reader.query()
    assert not reader.db_path.exists()
