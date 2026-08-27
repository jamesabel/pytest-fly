"""psutil handle reuse: repeated subtree sampling must not reconstruct psutil.Process handles.

Constructing a ``psutil.Process`` runs a native init (a ``create_time`` identity read).  A native
access-violation crash during garbage collection (Windows, Python 3.14) was observed with exactly
those construction frames on the stack, so the samplers construct a handle once at first sight of
a pid and reuse it: ``subtree_pids``/``subtree_process_count`` walk a pid→ppid snapshot with zero
constructions, ``SubtreeCpuSampler`` and ``subtree_commit`` (with a ``ProcessHandleCache``)
construct per pid at most once across samples.

All tests, fixtures, helpers, and constants in this module are AI-authored (Claude Code); the
per-test ownership markers below apply to the private helpers and constants as well.
"""

import subprocess
import sys
import time
from collections import Counter

import psutil
import pytest

from pytest_fly.pytest_runner.commit_memory import ProcessHandleCache, subtree_commit, subtree_pids, subtree_process_count
from pytest_fly.pytest_runner.process_monitor import SubtreeCpuSampler

# Root spawns one grandchild-of-the-test and sleeps, giving a stable 2-process tree
# (root + descendant) that spawns nothing new while a test samples it repeatedly.
_TREE_SRC = "import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']); time.sleep(120)"

_TREE_SIZE = 2  # the spawned root plus its one child
_SPAWN_TIMEOUT = 15.0


def _kill_tree(root: subprocess.Popen) -> None:
    """Tear down the spawned tree: descendants first, then the root."""
    try:
        for child in psutil.Process(root.pid).children(recursive=True):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
    except psutil.NoSuchProcess:
        pass
    root.kill()
    root.wait(timeout=10)


def _wait_for_tree(root_pid: int) -> None:
    """Block until the root's child exists (the tree is fully spawned)."""
    deadline = time.time() + _SPAWN_TIMEOUT
    while len(subtree_pids(root_pid)) < _TREE_SIZE:
        assert time.time() < deadline, f"spawned tree did not reach {_TREE_SIZE} processes in {_SPAWN_TIMEOUT}s"
        time.sleep(0.1)


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
@pytest.fixture
def process_tree():
    """Spawn the 2-process tree and yield the root pid; tear the tree down afterwards."""
    root = subprocess.Popen([sys.executable, "-c", _TREE_SRC])
    try:
        _wait_for_tree(root.pid)
        yield root.pid
    finally:
        _kill_tree(root)


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
@pytest.fixture
def counting_process_class(monkeypatch):
    """Replace ``psutil.Process`` with a subclass that records every construction's pid."""
    constructions: list[int | None] = []
    real_process = psutil.Process

    class CountingProcess(real_process):
        def __init__(self, pid=None):
            constructions.append(pid)
            super().__init__(pid)

    monkeypatch.setattr(psutil, "Process", CountingProcess)
    return constructions


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
def test_subtree_pids_matches_children_walk(process_tree):
    """subtree_pids reports the same membership as psutil's children(recursive=True) walk."""
    root_pid = process_tree
    via_children = {root_pid} | {p.pid for p in psutil.Process(root_pid).children(recursive=True)}
    members = subtree_pids(root_pid)
    assert members[0] == root_pid, "the root pid must be first"
    assert set(members) == via_children


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
def test_subtree_pids_missing_pid_fails_open():
    """A pid that cannot exist yields an empty membership and a zero count, never an exception."""
    assert subtree_pids(-1) == []
    assert subtree_process_count(-1) == 0


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
def test_subtree_process_count_constructs_no_handles(process_tree, counting_process_class):
    """Counting the tree is membership-only: zero psutil.Process constructions."""
    root_pid = process_tree
    assert subtree_process_count(root_pid) >= _TREE_SIZE
    assert counting_process_class == [], f"subtree_process_count constructed handles for pids {counting_process_class}"


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
def test_sampler_constructs_each_pid_once(process_tree, counting_process_class):
    """Across repeated samples of a stable tree, each pid's handle is constructed at most once."""
    root_pid = process_tree
    sampler = SubtreeCpuSampler()
    assert sampler.sample(root_pid) is None  # first sight primes root + descendants
    time.sleep(0.2)
    assert sampler.sample(root_pid) is not None  # primed tree yields a real reading
    time.sleep(0.2)
    assert sampler.sample(root_pid) is not None
    per_pid = Counter(counting_process_class)
    assert per_pid and max(per_pid.values()) == 1, f"handles reconstructed across samples: {[p for p, n in per_pid.items() if n > 1]}"


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
def test_sampler_drops_departed_handles(process_tree):
    """A descendant that exits is dropped from the sampler's handle cache on the next sample."""
    root_pid = process_tree
    sampler = SubtreeCpuSampler()
    sampler.sample(root_pid)  # prime: caches root + descendant handles
    descendant_pids = [member_pid for member_pid in subtree_pids(root_pid) if member_pid != root_pid]
    assert descendant_pids, "expected at least one descendant"
    for descendant_pid in descendant_pids:
        assert descendant_pid in sampler._procs
        psutil.Process(descendant_pid).kill()
    deadline = time.time() + _SPAWN_TIMEOUT
    while any(pid in sampler._procs for pid in descendant_pids):
        assert time.time() < deadline, "departed descendant handles were not dropped"
        time.sleep(0.1)
        sampler.sample(root_pid)


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
def test_subtree_commit_with_cache_constructs_each_pid_once(process_tree, counting_process_class):
    """With a persistent ProcessHandleCache, repeated commit reads construct each handle at most once."""
    root_pid = process_tree
    handle_cache = ProcessHandleCache()
    assert subtree_commit(root_pid, handle_cache) > 0
    assert subtree_commit(root_pid, handle_cache) > 0
    per_pid = Counter(counting_process_class)
    assert per_pid and max(per_pid.values()) == 1, f"handles reconstructed across commit reads: {[p for p, n in per_pid.items() if n > 1]}"
