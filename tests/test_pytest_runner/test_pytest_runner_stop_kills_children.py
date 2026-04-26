import os
import time
from pathlib import Path

import psutil

from pytest_fly.guid import generate_uuid
from pytest_fly.interfaces import ScheduledTest
from pytest_fly.pytest_runner import PytestRunner

from ..paths import get_temp_dir

_FIXTURE_TEST_SOURCE = """\
import os
import subprocess
import sys
import time


def test_spawns_child():
    pid_file = os.environ["PYTEST_FLY_CHILD_PID_FILE"]
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    with open(pid_file, "w") as f:
        f.write(str(child.pid))
    time.sleep(120)
    assert True
"""


def _wait_pid_gone(pid: int, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not psutil.pid_exists(pid):
            return True
        time.sleep(0.1)
    return not psutil.pid_exists(pid)


def test_pytest_runner_stop_kills_children(app, tmp_path):

    test_name = "test_pytest_runner_stop_kills_children"
    data_dir = get_temp_dir(test_name)
    run_guid = generate_uuid()

    # Write the fixture test to tmp_path so it's never collected by the regular
    # suite (a real test_*.py file would always show up as SKIPPED).
    fixture_file = Path(tmp_path, "test_spawns_child.py")
    fixture_file.write_text(_FIXTURE_TEST_SOURCE)
    pid_file = Path(tmp_path, "child.pid")
    os.environ["PYTEST_FLY_CHILD_PID_FILE"] = str(pid_file)
    try:
        scheduled_tests = [ScheduledTest(node_id=str(fixture_file), singleton=False, duration=None, coverage=None)]

        runner = PytestRunner(run_guid, scheduled_tests, number_of_processes=1, data_dir=data_dir, update_rate=1.0)
        runner.start()

        # wait until the test has spawned its child and recorded the PID
        deadline = time.time() + 30.0
        while time.time() < deadline and not pid_file.exists():
            time.sleep(0.2)
        assert pid_file.exists(), "test_spawns_child never wrote its child pid"
        child_pid = int(pid_file.read_text().strip())
        assert psutil.pid_exists(child_pid), f"child pid {child_pid} was not running before stop"

        runner.stop()
        runner.join(15.0)

        assert _wait_pid_gone(child_pid), f"orphaned child pid {child_pid} still alive after runner.stop()"
    finally:
        os.environ.pop("PYTEST_FLY_CHILD_PID_FILE", None)
