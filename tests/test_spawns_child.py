"""
Test fixture used by test_pytest_runner_stop_kills_children — spawns a long-sleeping
child process and writes its PID to a known file, then sleeps so the runner can stop it.
This file is intentionally excluded from normal test runs (it would just sleep);
its callers run it directly via pytest_fly.
"""

import os
import subprocess
import sys
import time

import pytest


@pytest.mark.skipif(os.environ.get("PYTEST_FLY_SPAWN_CHILD_TEST") != "1", reason="invoked only by the runner stop test")
def test_spawns_child():
    pid_file = os.environ["PYTEST_FLY_CHILD_PID_FILE"]
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    with open(pid_file, "w") as f:
        f.write(str(child.pid))
    time.sleep(120)
    assert True
