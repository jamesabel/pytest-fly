"""The per-test CPU% the monitor reports must include the test's subprocesses.

``ProcessMonitor`` samples one target process (in production, a test's ``pytest`` subprocess) and
feeds the table's CPU% column.  A test often offloads its real work to a spawned subprocess/.exe, so
the monitor sums CPU across the whole process subtree.  This guards that the busy descendant's CPU is
actually counted — it would read ~0 if only the (idle) target process were sampled.
"""

import os
import subprocess
import sys
import time
from pathlib import Path
from queue import Empty

import psutil

from pytest_fly.pytest_runner.process_monitor import ProcessMonitor

from .paths import get_temp_dir

# Recursive spawner: each level Popens the next; the leaf burns one core. Mirrors a test that
# launches an application -> subprocess -> busy .exe.  argv: <remaining:int> <stop_file>.
_CHAIN_SRC = """\
import os, sys, time, subprocess

remaining = int(sys.argv[1])
stop_file = sys.argv[2]
safety_deadline = time.time() + 60.0

if remaining > 0:
    child = subprocess.Popen([sys.executable, __file__, str(remaining - 1), stop_file])
    while not os.path.exists(stop_file) and time.time() < safety_deadline:
        time.sleep(0.2)  # idle ancestor; near-zero CPU
    child.terminate()
else:
    x = 0
    while not os.path.exists(stop_file) and time.time() < safety_deadline:
        x += 1  # one full core busy
"""

_DEPTH = 3  # root + 3 generations: the busy leaf is a great-grandchild of the monitored root


def test_process_monitor_counts_busy_descendant_cpu():
    """A CPU-busy great-grandchild is reflected in the monitor's reported CPU%, even though the
    monitored root and the intermediate processes are idle."""
    work_dir = get_temp_dir("process_monitor_cpu_subtree")
    helper = Path(work_dir, "mon_chain.py")
    helper.write_text(_CHAIN_SRC, encoding="utf-8")
    stop_file = Path(work_dir, f"stop_{os.getpid()}.flag")
    stop_file.unlink(missing_ok=True)

    root = subprocess.Popen([sys.executable, str(helper), str(_DEPTH), str(stop_file)])
    monitor = ProcessMonitor("test-run-guid", "tests/test_x.py", root.pid, update_rate=0.3)
    try:
        monitor.start()
        time.sleep(4.0)  # gather several samples; the leaf primes on first sight, reads real after
        monitor.request_stop()
        monitor.join(10.0)

        cpu_samples = []
        while True:
            try:
                info = monitor.process_monitor_queue.get(timeout=0.2)
            except Empty:
                break
            if info.cpu_percent is not None:
                cpu_samples.append(info.cpu_percent)

        assert cpu_samples, "monitor produced no CPU samples"
        peak = max(cpu_samples)
        # One fully-busy descendant core reads ~100 on psutil's raw scale; the idle root + idle
        # intermediates alone would be near 0. A generous floor keeps this robust across machines.
        assert peak > 50.0, f"busy descendant CPU not counted in subtree sample (peak={peak})"
    finally:
        stop_file.write_text("stop", encoding="utf-8")
        if monitor.is_alive():
            monitor.request_stop()
            monitor.join(5.0)
            if monitor.is_alive():
                monitor.kill()
        try:
            proc = psutil.Process(root.pid)
            for child in proc.children(recursive=True):
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            proc.kill()
        except psutil.NoSuchProcess:
            pass
        try:
            root.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
