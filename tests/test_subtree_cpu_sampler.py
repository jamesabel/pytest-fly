"""Does the "Idle" metric account for a deeply-nested external executable?

A user's test launches an *application*, which spawns a *subprocess*, which ``Popen``s an external
``.exe`` that does the real CPU work.  The stall watchdog samples the test's process via
``_StallWatchdog._default_cpu_sampler`` (``pytest_runner.py``), summing the process plus
``children(recursive=True)`` — the whole subtree at any depth — and flags the test idle only when
that total is at/below ``cpu_active_epsilon``.

These tests build the exact 4-level tree and drive the *real* production path:

    root  (the sampled "pytest test process")
      -> A      ("application")
          -> B  ("subprocess")
              -> L  the ".exe" — sys.executable (a genuine external executable), busy or idle

and assert (a) the great-grandchild leaf is reachable in the recursive subtree walk and (b) a
CPU-busy leaf makes the metric report the test as active (subtree CPU above epsilon, root not in
``idle_pids``), while an idle leaf reports it as idle.  ``sys.executable`` stands in for a real
compiled ``.exe``; swapping in one later is a one-line change to the leaf ``Popen`` target.
"""

import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import psutil

from pytest_fly.pytest_runner.commit_memory import subtree_process_count
from pytest_fly.pytest_runner.pytest_runner import _StallConfig, _StallWatchdog

from .paths import get_temp_dir

# Recursive spawner. argv: <remaining:int> <stop_file> <leaf_mode:"busy"|"idle">.
# Each level Popens the next; the leaf (remaining == 0) either burns one core or idles. Every level
# exits when the stop file appears, with a safety deadline so no orphan can outlive a crashed test.
_CHAIN_HELPER_SRC = """\
import os, sys, time, subprocess

remaining = int(sys.argv[1])
stop_file = sys.argv[2]
leaf_mode = sys.argv[3]
safety_deadline = time.time() + 60.0

if remaining > 0:
    child = subprocess.Popen([sys.executable, __file__, str(remaining - 1), stop_file, leaf_mode])
    while not os.path.exists(stop_file) and time.time() < safety_deadline:
        time.sleep(0.2)  # near-zero CPU; keeps this ancestor link alive
    child.terminate()
elif leaf_mode == "busy":
    x = 0
    while not os.path.exists(stop_file) and time.time() < safety_deadline:
        x += 1  # one full core busy
else:
    while not os.path.exists(stop_file) and time.time() < safety_deadline:
        time.sleep(0.2)  # idle leaf
"""

_DEPTH = 3  # root + 3 generations: the leaf ".exe" is a great-grandchild of the sampled root
_EXPECTED_TREE_SIZE = _DEPTH + 1
_EPSILON = _StallConfig().cpu_active_epsilon  # 1.0% single-core-equiv


def _make_sampling_watchdog(root_pid: int) -> _StallWatchdog:
    """A watchdog using the real default CPU sampler, with only the progress source faked.

    The injected progress source reports ``root_pid`` as the single in-flight ("RUNNING") test, so
    ``tick`` evaluates the production idle logic against the live process tree.
    """
    return _StallWatchdog(
        "test-run-guid",
        Path("."),
        controller_pid=None,
        config=_StallConfig(),
        is_running_fn=lambda: True,
        escalate_fn=lambda: None,
        sample_interval=1.0,
        progress_source=lambda: ((0, 1, 0.0), ["tests/test_x.py"], [root_pid], 1),
        # cpu_sampler left default => exercises the real _default_cpu_sampler subtree walk
    )


@contextmanager
def _process_chain(leaf_mode: str):
    """Spawn root -> A -> B -> leaf and yield the root pid; tear the whole tree down on exit."""
    work_dir = get_temp_dir("subtree_cpu_sampler")
    helper_path = Path(work_dir, "cpu_chain_helper.py")
    helper_path.write_text(_CHAIN_HELPER_SRC, encoding="utf-8")
    stop_file = Path(work_dir, f"stop_{leaf_mode}_{os.getpid()}.flag")
    stop_file.unlink(missing_ok=True)

    root = subprocess.Popen([sys.executable, str(helper_path), str(_DEPTH), str(stop_file), leaf_mode])
    try:
        yield root.pid
    finally:
        stop_file.write_text("stop", encoding="utf-8")  # signal every level to exit cleanly
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


def _wait_for_full_tree(root_pid: int, timeout: float = 10.0) -> int:
    """Block until the whole 4-level tree exists, returning the final subtree count.

    Doubles as a deterministic check that the great-grandchild leaf is reachable via the recursive
    subtree walk the CPU sampler relies on.
    """
    deadline = time.time() + timeout
    count = subtree_process_count(root_pid)
    while count < _EXPECTED_TREE_SIZE and time.time() < deadline:
        time.sleep(0.1)
        count = subtree_process_count(root_pid)
    return count


def _poll_subtree_cpu(root_pid: int, want_above_epsilon: bool, timeout: float = 12.0) -> float | None:
    """Prime then poll the real subtree CPU sampler until it crosses (or stays below) epsilon.

    Returns the deciding reading, or None if the target condition was never observed in time.
    """
    wd = _make_sampling_watchdog(root_pid)
    assert wd._cpu_sampler(root_pid) is None  # first reading primes root + all current descendants
    deadline = time.time() + timeout
    last: float | None = None
    while time.time() < deadline:
        time.sleep(0.5)
        value = wd._cpu_sampler(root_pid)
        if value is None:
            continue
        last = value
        if (value > _EPSILON) == want_above_epsilon:
            return value
    return last if (last is not None and (last > _EPSILON) == want_above_epsilon) else None


def _root_idle_via_metric(root_pid: int, want_idle: bool, attempts: int = 8) -> bool:
    """Drive the production idle metric (StallWatchdog.tick -> idle_pids) and report whether the
    root's idle membership reached ``want_idle`` within a few ticks."""
    wd = _make_sampling_watchdog(root_pid)
    wd.tick()  # prime (sampler returns None for newly-seen pids)
    for _ in range(attempts):
        time.sleep(0.5)
        wd.tick()
        info = wd.get_stall_info()
        if (root_pid in (info.idle_pids or [])) == want_idle:
            return True
    return False


def test_idle_metric_excludes_busy_deep_exe():
    """A CPU-busy great-grandchild .exe is counted: subtree CPU exceeds epsilon and the test is not
    flagged idle by the production metric."""
    with _process_chain("busy") as root_pid:
        size = _wait_for_full_tree(root_pid)
        assert size >= _EXPECTED_TREE_SIZE, f"deep .exe not reachable in subtree walk (size={size}, want >= {_EXPECTED_TREE_SIZE})"

        cpu = _poll_subtree_cpu(root_pid, want_above_epsilon=True)
        assert cpu is not None and cpu > _EPSILON, f"busy deep .exe CPU was not counted in the subtree sample (last={cpu}, epsilon={_EPSILON})"

        assert _root_idle_via_metric(root_pid, want_idle=False), "busy test was wrongly flagged idle despite a CPU-burning great-grandchild .exe"


def test_idle_metric_flags_idle_deep_exe():
    """Control: with an idle leaf the whole subtree reads idle and the production metric flags the
    test idle — proving the busy result is driven by the deep .exe's CPU, not tree overhead."""
    with _process_chain("idle") as root_pid:
        size = _wait_for_full_tree(root_pid)
        assert size >= _EXPECTED_TREE_SIZE, f"deep .exe not reachable in subtree walk (size={size}, want >= {_EXPECTED_TREE_SIZE})"

        assert _root_idle_via_metric(root_pid, want_idle=True), "idle test tree was not flagged idle by the production metric"
